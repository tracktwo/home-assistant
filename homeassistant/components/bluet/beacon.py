"""Implementation of a BlueT device beacon."""


from __future__ import annotations

from datetime import datetime
import logging
import struct

from Crypto.Cipher import AES
from home_assistant_bluetooth import BluetoothServiceInfoBleak
import numpy as np

from .const import EDDYSTONE_SERVICE_UUID

_LOGGER = logging.getLogger(__name__)


class EidEntry:
    """A cached EID entry."""

    count: np.uint32
    eid: bytes

    def __init__(self, count: np.uint32, eid: bytes) -> None:
        """Construct an EID entry with the given EID and count."""
        self.count = count
        self.eid = eid


class BlueTDevice:
    """Representation of a BlueT device."""

    name: str
    identity_key: bytes
    exponent: np.uint32
    count: np.uint32
    window_size: int
    temperature: float
    signal_strength: int
    battery: int
    advertising_count: int
    uptime: int
    last_seen: datetime | None
    new_data_available: bool
    address: str | None

    _eids: list[EidEntry]
    _resync_eids: list[EidEntry]

    def __init__(
        self,
        name: str,
        identity_key: bytes,
        exponent: int,
        count: int,
        window_size: int,
        last_seen: datetime | None,
    ) -> None:
        """Construct a new beacon instance."""
        self.name = name
        self.identity_key = identity_key
        self.exponent = np.uint32(exponent)
        # Ensure the count is properly masked.
        self.count = np.uint32(count & ~((1 << self.exponent) - 1))
        self.window_size = window_size
        self.last_seen = last_seen

        self.temperature = 0
        self.signal_strength = 0
        self.battery = 0
        self.advertising_count = 0
        self.uptime = 0
        self.new_data_available = False
        self._resync_eids = []
        self.address = None

        # Compute the EID window for the current count
        self._eids = self._compute_eids(self.count)

    def process_packet(self, packet: BluetoothServiceInfoBleak):
        """Process a packet.

        This packet may or may not be for this device.
        """
        data = packet.service_data[EDDYSTONE_SERVICE_UUID]
        assert data is not None

        # The packet type is in the first byte of the service data
        if data[0] == 0:
            # UID. Not handled by this implementation
            return
        if data[0] == 0x10:
            # URL. Not handled by this implementation.
            return
        if data[0] == 0x20:
            # TLM. Could be encrypted or unencrypted. Only processed if
            # this device's address matches the packet.
            if self.address == packet.address:
                if data[1] != 1:
                    # Not an ETLM packet. Not handled by this implementation.
                    return
                self._process_etlm(data, packet.rssi)
            return
        if data[0] == 0x30:
            # EID
            self._process_eid(data, packet.address)
            return

    def _process_eid(self, data: bytes, address: str):
        """Process the given bytes for an EID packet."""

        # Check staleness.
        self._check_stale_eids()

        # The EID packget should be 10 bytes long, with the encrypted EID
        # payload in the last 8 bytes
        assert len(data) == 10
        received_eid = data[2:]
        for i, entry in enumerate(self._eids):
            if entry.eid == received_eid:
                self._handle_eid_match(i, address)
                return

        # No match in the current EID window. If we have a resync list, check
        # that too.
        if len(self._resync_eids) > 0:
            for i, entry in enumerate(self._resync_eids):
                if entry.eid == received_eid:
                    # We had a hit in the resync list. Move the resync list
                    # to the current EID list and run the usual update.
                    self._eids = self._resync_eids
                    self._resync_eids = []
                    self._handle_eid_match(i, address)

    def _handle_eid_match(self, index, address):
        """Handle an EID match."""
        # We have a match - update the last seen time and remember the
        # device address.
        _LOGGER.debug(
            "Got EID match for %s at %s position %s",
            self.name,
            self._eids[index].count,
            index,
        )
        self.last_seen = datetime.utcnow()
        self.address = address

        while index < self.window_size:
            # Add a new entry at the front of the list for the masked
            # count prior to the existing first entry.
            new_count = np.uint32(self._eids[0].count - 2**self.exponent)
            self._eids.insert(0, EidEntry(new_count, self._compute_eid_at(new_count)))
            self._eids.pop()
            index += 1

        while index > self.window_size:
            # Add a new entry at the end of the list for the masked
            # count after the existing last entry.
            new_count = np.uint32(self._eids[-1].count + 2**self.exponent)
            self._eids.append(EidEntry(new_count, self._compute_eid_at(new_count)))
            self._eids.pop(0)
            index -= 1

        assert len(self._eids) == 2 * self.window_size + 1
        self.count = self._eids[self.window_size].count

    def _process_etlm(self, data: bytes, rssi: int):
        """Process the given bytes for an ETLM packet."""

        # The ETLM packet should be 18 bytes long
        assert len(data) == 18

        # The ciphertext immediately follows the "header" portion with frame
        # type and version.
        ciphertext = data[2:14]

        # Construct the nonce: 32 bits for count followed by the 16 bit random
        # salt available in the packet. The count should have been adjusted by
        # the last successful EID packet match so should be the same as the
        # one used in this decode.
        nonce = struct.pack(">I", int(self.count)) + data[14:16]
        cipher = AES.new(self.identity_key, AES.MODE_EAX, nonce=nonce)
        try:
            # Decrypt the ciphertext with no verification. PyCryptome does not
            # support MACs with length < 32 bits, but Eddystone uses 16 bit.
            # So: decrypt, then re-encrypt with the same nonce to generate a
            # ful-length tag. Then compare the top 2 bytes of the generated tag
            # with the one we received.
            plaintext = cipher.decrypt(ciphertext)
            verify_cipher = AES.new(self.identity_key, AES.MODE_EAX, nonce=nonce)
            _, tag = verify_cipher.encrypt_and_digest(plaintext)  # type: ignore[union-attr]
            if tag[0:2] != data[16:18]:
                _LOGGER.info(
                    "Sensor %s failed verification of ETLM packet at count %s",
                    self.name,
                    self.count,
                )
                return
        except (KeyError, ValueError):
            # The digest failed to verify. No TLM update
            _LOGGER.info(
                "Sensor %s failed to decrypt ETLM packet at count %s",
                self.name,
                self.count,
            )
            return

        # Unpack the plaintext payload and set the device state
        assert len(plaintext) == 12
        batt, temp, adv, uptime = struct.unpack(">HHII", plaintext)

        _LOGGER.debug(
            "Decrypted ETLM packet for %s to [%s mV, %s C, %s adv, %s s]",
            self.name,
            batt,
            temp / 256,
            adv,
            uptime,
        )

        # Convert the temperature back to a float from the 8.8 fixed point value
        # The rest are all in immediately usable form.
        self.temperature = temp / 256
        self.battery = batt
        self.advertising_count = adv
        self.uptime = uptime
        self.signal_strength = rssi

        # Set a flag indicating new data is available to be read.
        self.new_data_available = True

    def _compute_eids(self, count) -> list[EidEntry]:
        """Pre-compute a window of EIDs for this device."""

        # The count should always have the lowest 'exponent' bits clear.
        assert count & ~((np.uint32(1) << self.exponent) - 1) == count
        # Determine the count that would have been used for the earliest entry
        # in our window. Each entry lasts for 2^K seconds.
        tmp_count: np.uint32 = np.uint32(
            count - (self.window_size * (2**self.exponent))
        )

        # Take the top 16 bits of the count for temporary key generation
        upper_count: np.uint16 = np.uint16(tmp_count >> 16)

        temporary_key = self._compute_temporary_key(upper_count)

        eids = []

        # We want `window_size` entries on either side of the EID for the current
        # count.
        for _ in range(self.window_size * 2 + 1):
            eids.append(
                EidEntry(
                    count=tmp_count, eid=self._compute_eid(tmp_count, temporary_key)
                )
            )
            # Move to the count corresponding to the next EID
            tmp_count += np.uint32(2**self.exponent)
            # If this new count needs a new temporary key, generate it.
            if upper_count != tmp_count >> 16:
                upper_count = np.uint16(tmp_count >> 16)
                temporary_key = self._compute_temporary_key(upper_count)
        return eids

    def _compute_temporary_key(self, upper_count: np.uint16) -> bytes:
        """Compute the temporary key for the given upper 16 bits of `count`."""

        # The temporary key is the AES-encrypted result with the identity key of:
        # 11 null bytes
        # 0xFF
        # 2 null bytes
        # The upper 16 bits of the count as a big-endian number
        plaintext: bytes = struct.pack(">11xB2xH", 0xFF, upper_count)
        cipher = AES.new(self.identity_key, AES.MODE_ECB)
        return cipher.encrypt(plaintext)

    def _compute_eid_at(self, count: np.uint32):
        """Compute the EID at the given count."""

        # The lowest 'exponent' bits should be clear.
        assert count & ~((np.uint32(1) << self.exponent) - 1) == count

        upper_count: np.uint16 = np.uint16(count >> 16)
        temporary_key = self._compute_temporary_key(upper_count)
        return self._compute_eid(count, temporary_key)

    def _compute_eid(self, count: np.uint32, temporary_key: bytes) -> bytes:
        """Compute an EID for the given count with the given temporary key."""

        # The lowest 'exponent' bits of count should be zero.
        assert count & ~((1 << self.exponent) - 1) == count

        # The encrypted EID is the AES-encrypted result with the temporary key of:
        # 11 null bytes
        # the exponent 'K'
        # the counter with the lowest 'K' bits cleared
        plaintext: bytes = struct.pack(">11xBI", self.exponent, np.uint32(count))
        cipher = AES.new(temporary_key, AES.MODE_ECB)

        # The EID is the upper 64 bits of the encryption
        eid = cipher.encrypt(plaintext)[0:8]
        _LOGGER.debug(
            "Computed new EID for %s at count %s: %s", self.name, self.count, eid
        )
        return eid

    def _check_stale_eids(self):
        """Build a stale EID list if the current EID list is very stale."""

        if self.last_seen:
            delta = datetime.utcnow() - self.last_seen
            seconds_since_last_seen = delta.total_seconds()

            # Add the current time delta to the count at the center of the
            # EID window, and mask off the bottom exponent bits. This is the
            # count we would expect the next EID to be broadcast in.
            expected_count = np.uint32(
                self._eids[self.window_size].count + seconds_since_last_seen
            )
            expected_count = expected_count & ~((1 << self.exponent) - 1)

            # If the expected count is bigger than the count at the very end
            # of our window then we haven't seen anything from the beacon in
            # a really long time. This could be because the beacon disappeared,
            # or because this receiver disappeared. If the beacon disappeared
            # there is nothing to do, because it should broadcast using that
            # old EID. If this receiver disappeared then we can recover by
            # computing an expected EID window around this expected count.
            # If both disappeared and came back at different times then we
            # may or may not be able to resync, depending on how out of sync
            # the two got.
            if expected_count > self._eids[-1].count:

                # If we already have a resync list for this count then there isn't
                # anything to do.
                if (
                    len(self._resync_eids) > 0
                    and self._resync_eids[self.window_size] == expected_count
                ):
                    return

                # Build a resync list.
                self._resync_eids = self._compute_eids(expected_count)
