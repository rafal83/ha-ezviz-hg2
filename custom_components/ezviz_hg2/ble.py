"""Authenticated local BLE control for EZVIZ HG2 gate controllers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging

from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)
from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

SERVICE_UUID = "0000fccc-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000fed5-0000-1000-8000-00805f9b34fb"
INDICATE_UUID = "0000fed6-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fed8-0000-1000-8000-00805f9b34fb"
AUTH_WRITE_UUID = "0000fed9-0000-1000-8000-00805f9b34fb"
TRANSPORT_UUID = "0000fedb-0000-1000-8000-00805f9b34fb"

CMD_COMMON_REPLY = 0x0101
CMD_SEND_TRANSPORT = 0x0502
CMD_LOCAL_AUTH_PUBKEY = 0x2007
CMD_LOCAL_AUTH_CHECK = 0x2008

_IV = b"1234567800000000"
_ACTION_VALUES = {"open": 100, "pause": 255, "close": 0}
_CONNECTION_ATTEMPTS = 2
_CONNECTION_TIMEOUT = 8.0
_AUTH_SETTLE_DELAY = 1.0


class EzvizHg2BleError(RuntimeError):
    """Raised when authenticated HG2 BLE control fails."""


@dataclass(frozen=True)
class _Frame:
    command: int
    payload: bytes
    sequence: int
    total_fragment: int | None = None


def _aes_encrypt(key: bytes, plaintext: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(_IV)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _aes_decrypt(key: bytes, ciphertext: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.CBC(_IV)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def _make_tlv(kind: int, value: bytes, soft_version: int) -> bytes:
    if soft_version == 4:
        return bytes([kind]) + len(value).to_bytes(2, "little") + value
    if len(value) > 255:
        raise EzvizHg2BleError("BLE authentication value is too long")
    return bytes([kind, len(value)]) + value


def _parse_tlvs(data: bytes, soft_version: int) -> dict[int, bytes]:
    fields: dict[int, bytes] = {}
    cursor = 0
    length_size = 2 if soft_version == 4 else 1
    while cursor < len(data):
        if cursor + 1 + length_size > len(data):
            raise EzvizHg2BleError("Truncated BLE authentication response")
        kind = data[cursor]
        length_start = cursor + 1
        length = int.from_bytes(
            data[length_start : length_start + length_size], "little"
        )
        value_start = length_start + length_size
        value_end = value_start + length
        if value_end > len(data):
            raise EzvizHg2BleError("Truncated BLE authentication value")
        if length:
            fields[kind] = data[value_start:value_end]
        cursor = value_end
    return fields


def _little_int(value: bytes | None, default: int = -1) -> int:
    return int.from_bytes(value, "little") if value else default


def _build_frame(
    command: int,
    payload: bytes = b"",
    *,
    sequence: int,
    soft_version: int,
    session_key: bytes | None = None,
) -> bytes:
    command_payload = command.to_bytes(2, "little") + payload
    if session_key is not None:
        command_payload = _aes_encrypt(session_key, command_payload)
    control = bytes([0, 1 if session_key is not None else 0])
    body = control + bytes([sequence & 0xFF]) + command_payload
    encoded_length = len(body) + 1
    if soft_version > 2:
        length_field = encoded_length.to_bytes(2, "little")
    else:
        if encoded_length > 255:
            raise EzvizHg2BleError("BLE frame is too long")
        length_field = bytes([encoded_length])
    partial = b"\xaa\x55" + length_field + body
    return partial + bytes([sum(partial[3:]) & 0xFF])


def _parse_frame(
    data: bytes, *, soft_version: int, session_key: bytes | None
) -> _Frame:
    if len(data) < 9 or data[:2] != b"\xaa\x55":
        raise EzvizHg2BleError("Invalid BLE response header")
    if soft_version > 2:
        declared_length = int.from_bytes(data[2:4], "little")
        control_offset = 4
        expected_length = declared_length + 4
    else:
        declared_length = data[2]
        control_offset = 3
        expected_length = declared_length + 3
    if len(data) != expected_length:
        raise EzvizHg2BleError("Invalid BLE response length")
    if (sum(data[3:-1]) & 0xFF) != data[-1]:
        raise EzvizHg2BleError("Invalid BLE response checksum")

    control0, control1 = data[control_offset : control_offset + 2]
    cursor = control_offset + 2
    total_fragment = None
    if control0 & 0x80:
        if cursor + 4 >= len(data):
            raise EzvizHg2BleError("Truncated fragmented BLE response")
        total_fragment = int.from_bytes(data[cursor : cursor + 2], "little")
        cursor += 4
    sequence = data[cursor]
    command_payload = data[cursor + 1 : -1]
    if control1 & 0x01:
        if session_key is None:
            raise EzvizHg2BleError("Encrypted BLE response has no session key")
        command_payload = _aes_decrypt(session_key, command_payload)
    if len(command_payload) < 2:
        raise EzvizHg2BleError("BLE response contains no command")
    return _Frame(
        command=int.from_bytes(command_payload[:2], "little"),
        payload=command_payload[2:],
        sequence=sequence,
        total_fragment=total_fragment,
    )


def _build_motor_frame(action: str, sequence: int = 0) -> bytes:
    try:
        action_value = _ACTION_VALUES[action]
    except KeyError as err:
        raise EzvizHg2BleError(f"Unsupported BLE gate action: {action}") from err
    payload = bytes((0x1A, 0x27, 0x01, 0x00, 0x00, action_value))
    frame = bytearray((0xAA, 0x10, 0x02, 0x00))
    frame.extend((len(payload) + 2).to_bytes(2, "little"))
    frame.extend((sequence & 0xFFFF).to_bytes(2, "little"))
    frame.extend(payload)
    frame.append(sum(frame[2:]) & 0xFF)
    frame.append(0)
    return bytes(frame)


def _validate_motor_response(data: bytes) -> None:
    if not data.startswith(b"\xaa\x10") or len(data) < 14:
        raise EzvizHg2BleError("Unexpected HG2 BLE command response")
    if data[8] != 0x1A or data[9] != 0x27 or data[10] != 0x02:
        raise EzvizHg2BleError("Unexpected HG2 BLE response command")
    if any(data[11:14]):
        raise EzvizHg2BleError(
            f"HG2 rejected the BLE command (code {data[11:14].hex()})"
        )


class _BleSession:
    def __init__(
        self, client: BleakClientWithServiceCache, timeout: float
    ) -> None:
        self._client = client
        self._timeout = timeout
        self._soft_version = 2
        self._sequence = 0
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    def _notification(self, _sender: object, data: bytearray) -> None:
        self._queue.put_nowait(bytes(data))

    async def async_start(self) -> None:
        services = {service.uuid.lower() for service in self._client.services}
        characteristics = {
            characteristic.uuid.lower()
            for service in self._client.services
            for characteristic in service.characteristics
        }
        if SERVICE_UUID not in services:
            raise EzvizHg2BleError("The device does not expose the EZVIZ BLE service")
        required = {WRITE_UUID, NOTIFY_UUID, AUTH_WRITE_UUID, TRANSPORT_UUID}
        if missing := sorted(required - characteristics):
            raise EzvizHg2BleError(
                "The device is missing EZVIZ BLE characteristics: "
                + ", ".join(missing)
            )
        await self._client.start_notify(NOTIFY_UUID, self._notification)
        if INDICATE_UUID in characteristics:
            await self._client.start_notify(INDICATE_UUID, self._notification)
        try:
            raw_transport = await self._client.read_gatt_char(TRANSPORT_UUID)
            transport = json.loads(bytes(raw_transport).decode("utf-8"))
            self._soft_version = int(transport.get("ezglp", 2))
            auth_mode = int(transport.get("auth_mode", -1))
        except (UnicodeDecodeError, ValueError, TypeError) as err:
            raise EzvizHg2BleError("Unreadable EZVIZ BLE transport data") from err
        if auth_mode != 3:
            raise EzvizHg2BleError(
                f"Unsupported EZVIZ BLE authentication mode: {auth_mode}"
            )

    async def async_request(
        self,
        command: int,
        payload: bytes = b"",
        *,
        session_key: bytes | None = None,
        auth_write: bool = False,
    ) -> _Frame:
        frame = _build_frame(
            command,
            payload,
            sequence=self._sequence,
            soft_version=self._soft_version,
            session_key=session_key,
        )
        self._sequence = (self._sequence + 1) & 0xFF
        write_uuid = AUTH_WRITE_UUID if auth_write else WRITE_UUID
        await self._client.write_gatt_char(write_uuid, frame, response=True)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise EzvizHg2BleError(
                    f"Timed out waiting for BLE command 0x{command:04x}"
                )
            try:
                raw = await asyncio.wait_for(self._queue.get(), remaining)
            except TimeoutError as err:
                raise EzvizHg2BleError(
                    f"Timed out waiting for BLE command 0x{command:04x}"
                ) from err
            response = _parse_frame(
                raw,
                soft_version=self._soft_version,
                session_key=session_key,
            )
            if response.total_fragment is not None:
                raise EzvizHg2BleError("Fragmented BLE responses are not supported")
            if response.command == command:
                return response
            if response.command == CMD_COMMON_REPLY:
                common = _parse_tlvs(response.payload, self._soft_version)
                if _little_int(common.get(2)) == command:
                    result = _little_int(common.get(3))
                    if result:
                        raise EzvizHg2BleError(
                            f"BLE command 0x{command:04x} was rejected (code {result})"
                        )
                    return response

    async def async_authenticate(self, serial: str, verify_code: str) -> bytes:
        private_key = ec.generate_private_key(ec.SECP256K1())
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )[1:]
        first = await self.async_request(
            CMD_LOCAL_AUTH_PUBKEY,
            _make_tlv(1, public_key, self._soft_version),
        )
        fields = _parse_tlvs(first.payload, self._soft_version)
        result = _little_int(fields.get(3))
        if result != 0:
            raise EzvizHg2BleError(
                f"HG2 BLE key exchange was rejected (code {result})"
            )
        device_public_raw = fields.get(1, b"")
        random_secret = fields.get(2, b"")
        if len(device_public_raw) != 64 or not random_secret:
            raise EzvizHg2BleError("Incomplete HG2 BLE key exchange response")
        if _little_int(fields.get(4), 0):
            raise EzvizHg2BleError(
                "This HG2 requires a BLE user identifier, which is not supported yet"
            )

        device_public = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256K1(), b"\x04" + device_public_raw
        )
        master_key = private_key.exchange(ec.ECDH(), device_public)[:16]
        random_value = _aes_decrypt(master_key, random_secret)
        session_key = hashlib.sha256(
            random_value
            + b"EZVIZ"
            + serial.encode("utf-8")
            + verify_code.encode("utf-8")
        ).digest()[:16]
        proof = _aes_encrypt(master_key, session_key)
        second = await self.async_request(
            CMD_LOCAL_AUTH_CHECK,
            _make_tlv(1, proof, self._soft_version),
        )
        result = _little_int(
            _parse_tlvs(second.payload, self._soft_version).get(2)
        )
        if result != 0:
            raise EzvizHg2BleError(
                "HG2 BLE authentication failed; check the verification code"
            )
        return session_key


class EzvizHg2BleController:
    """Send one authenticated local command to a configured HG2."""

    def __init__(
        self,
        hass: HomeAssistant,
        serial: str,
        verify_code: str,
        address: str | None,
        timeout: float,
    ) -> None:
        self._hass = hass
        self.serial = serial.upper()
        self._verify_code = verify_code
        self._address = address.upper() if address else None
        self._timeout = timeout
        self._lock = asyncio.Lock()

    def matches(self, serial: str) -> bool:
        """Return whether this controller is configured for a serial."""
        return self.serial == serial.upper()

    async def _async_find_device(self) -> BLEDevice:
        address = self._address
        if address is None:
            address = self._find_serial_address()
        device = (
            bluetooth.async_ble_device_from_address(
                self._hass, address, connectable=True
            )
            if address is not None
            else None
        )
        if device is None:
            if active_scan := getattr(
                bluetooth, "async_request_active_scan", None
            ):
                await active_scan(self._hass)
            if address is None:
                address = self._find_serial_address()
        if address is None:
            raise EzvizHg2BleError(
                f"HG2 {self.serial} was not discovered by Home Assistant Bluetooth"
            )
        device = bluetooth.async_ble_device_from_address(
            self._hass, address, connectable=True
        )
        if device is None:
            raise EzvizHg2BleError(
                f"HG2 {self.serial} is not reachable through a connectable "
                "Bluetooth adapter"
            )
        return device

    def _find_serial_address(self) -> str | None:
        for info in bluetooth.async_discovered_service_info(
            self._hass, connectable=True
        ):
            if self.serial.casefold() in (info.name or "").casefold():
                return info.address
        return None

    async def async_send(self, action: str) -> None:
        """Authenticate and send one open, close, or pause command."""
        if action not in _ACTION_VALUES:
            raise EzvizHg2BleError(f"Unsupported BLE gate action: {action}")
        await self._async_send_value(action, action)

    async def _async_send_value(self, value: str, description: str) -> None:
        """Retry connection setup, then send one motor value exactly once."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            started = loop.time()
            phase = "discovery"
            device = await self._async_find_device()
            discovered = loop.time()
            client: BleakClientWithServiceCache | None = None
            try:
                phase = "connection"
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    device,
                    device.name or self.serial,
                    max_attempts=_CONNECTION_ATTEMPTS,
                    timeout=min(self._timeout, _CONNECTION_TIMEOUT),
                )
                connected = loop.time()
                phase = "authentication"
                session = _BleSession(client, self._timeout)
                await session.async_start()
                session_key = await session.async_authenticate(
                    self.serial, self._verify_code
                )
                authenticated = loop.time()
                await asyncio.sleep(_AUTH_SETTLE_DELAY)
                phase = "motor command"
                response = await session.async_request(
                    CMD_SEND_TRANSPORT,
                    _build_motor_frame(value),
                    session_key=session_key,
                    auth_write=True,
                )
                _validate_motor_response(response.payload)
                finished = loop.time()
                _LOGGER.info(
                    "HG2 %s BLE timings: discovery %.2fs, connection %.2fs, "
                    "authentication %.2fs, stabilization %.2fs, command %.2fs, "
                    "total %.2fs",
                    self.serial,
                    discovered - started,
                    connected - discovered,
                    authenticated - connected,
                    _AUTH_SETTLE_DELAY,
                    finished - authenticated - _AUTH_SETTLE_DELAY,
                    finished - started,
                )
            except EzvizHg2BleError:
                raise
            except Exception as err:
                raise EzvizHg2BleError(
                    f"Unable to send {description} to HG2 {self.serial} over BLE "
                    f"during {phase} after {loop.time() - started:.1f}s: {err}"
                ) from err
            finally:
                if client is not None and client.is_connected:
                    try:
                        await client.disconnect()
                    except Exception:
                        _LOGGER.debug(
                            "Unable to disconnect cleanly from HG2 %s",
                            self.serial,
                            exc_info=True,
                        )
            _LOGGER.info(
                "Sent %s to HG2 %s through authenticated local BLE",
                description,
                self.serial,
            )
