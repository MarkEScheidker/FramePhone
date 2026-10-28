# Bluetooth connection

Bluetooth bonding and app trust are separate. The OS bond uses **Just Works**
without a verification number. After bonding, the apps establish **TLS 1.3 over
Bluetooth**, compare a hash, and save an application credential only after both
users approve. All application messages and motion packets travel inside TLS.

## First connection

1. Run FramePhone on Frame with Bluetooth enabled. An app with no remembered
   phone accepts the first phone connecting to its service.
2. On Android tap **Pair headset** and select **Steam Frame**. Android may ask
   for ordinary Pair consent; there is no Bluetooth code to compare or enter.
3. After OS bonding completes, both apps display the same hash. Compare the whole
   hash and select **Hashes match on both devices**. Either may approve first;
   the hash remains visible until enrollment completes. Reject cancels setup.
4. Only then is the application credential saved. The phone sends its LAN route
   over the verified TLS connection, and Frame connects over pinned Wi-Fi TLS.
   Both devices must already be on the same reachable network.
5. Later connections authenticate using the saved certificate and credential.
   There is no new hash prompt during an ordinary reconnect.

**Forget headset** on Android and **Forget phone** on Frame clear application
trust. The next connection needs a fresh hash approval on both devices. The
existing OS Bluetooth bond can remain; it is not the app's trust credential.
Frame rejects other radio identities while it remembers a phone. A forgotten or
reset app on the same Bluetooth device can enroll again with both hash approvals.

Disconnect stops Android's automatic connection service. Connect starts a fresh
attempt using saved app trust. Forget remains available after incomplete setup.
The upgrade from the former Bluetooth protocol requires one new hash exchange;
old application enrollment is not silently migrated.

## Transport and security

Frame registers a BlueZ `NoInputNoOutput` agent and an LE GATT service while the
app runs. The encrypted GATT permissions are `encrypt-read` / `encrypt-write`,
without a numeric-comparison or MITM requirement. This OS encryption is **not**
the application's authentication boundary.

Python's `ssl.MemoryBIO` and Android's `SSLEngine` carry standard TLS 1.3 over the
GATT byte transport. The existing phone Keystore identity serves both Bluetooth
TLS and Wi-Fi TLS. No custom cipher, key agreement or nonce scheme is implemented.

During enrollment, Frame sends a fresh 256-bit nonce through TLS, and the phone
returns another. Both compute SHA-256 over this ASCII transcript:

```
framephone-link-v2\nPHONE_CERTIFICATE_SHA256\nFRAME_NONCE\nPHONE_NONCE\n
```

The first 128 bits are displayed as eight groups of four hexadecimal digits.
The certificate and both nonces are included in the comparison. Until approval
on both sides, no credential is persisted, LAN route accepted, or motion delivered.
The phone generates a random 256-bit application credential after both approvals
and transfers it only through TLS. Frame saves its complete certificate pin and
credential atomically in a mode-0600 pairing file. Android stores a credential
verifier and stages an unacknowledged credential for interrupted enrollment.

On reconnect, Frame compares the TLS certificate with its saved pin **before
sending its credential**. Android authenticates the credential. If either app
forgot its trust or the certificate changed, a new hash exchange is required;
trust is never silently replaced. A rejected exchange preserves existing trust.
BLE pose delivery also requires binding to the exact authenticated Wi-Fi session.

The radio address only limits which remembered phone can reconnect. It is not
used as cryptographic identity. The Bluetooth bond may survive an application
Forget. If OS bond keys are manually removed from only one side, the platform may
require removing the stale bond on the other side too; the app does not modify
BlueZ's global repairing policy or use hidden Android bond-removal APIs.

### Bonding fails before the hash appears

App-level Forget does not remove the OS bond. If Android has no saved headset
but Frame still has the phone's old keys, BlueZ can reject Just Works re-pairing
before calling the app's agent. Restarting the apps does not clear these keys.

1. Close FramePhone on both devices.
2. In **Frame's system Bluetooth settings**, remove the phone's saved device.
3. In **Android's system Bluetooth settings**, forget Steam Frame if listed.
4. Open both apps, use app-level Forget if needed, and select **Pair headset**.

This resets only this device pair. The apps then create a fresh OS bond before
the TLS/hash exchange. BlueZ defaults to rejecting peer-initiated Just Works
re-pairing with an existing bond; see its
[repairing policy](https://github.com/bluez/bluez/blob/master/src/main.conf).

Frame enables incoming bonding while its agent is registered and restores any
adapter pairing settings it changed when the service closes. “Bluetooth ready”
requires successful agent, GATT and advertisement registration. Service loss
or an adapter power cycle triggers re-registration; setup errors remain visible
even after app-level Forget. Radio connection and completed bond are shown
separately from application hash verification.

## Wire format

Service UUID: `f7a10001-81a6-4c44-9c79-99ac54174901`. Control ends `0002`, pose ends
`0003`. Control reads carry up to 480 TLS bytes. GATT read-blob offsets use a
consistent snapshot. An empty read means no pending TLS output.

Control writes carry fragments with little-endian uint16 message ID, offset and
total length. An assembled fragment contains raw TLS bytes, not plaintext JSON.
Writes are ordered, bounded to 32 KiB and expire after three seconds without
progress. Pose writes
carry TLS bytes directly when they fit the negotiated MTU; larger TLS output uses
the same control fragmentation. TLS supplies integrity and replay protection.

Inside TLS, each application message is a big-endian uint32 length, a one-byte
type, then payload. Type 0 is JSON control; type 1 is the existing binary pose
packet. Messages are bounded to 64 KiB. The control exchange is:

- `hello` / `verification` / `confirm`: nonce exchange and explicit hash consent.
- `paired` / `enrolled` / `ready`: credential exchange, durable acknowledgment,
  and successful app authentication. Reconnect uses `hello(mode=reconnect)`.
- `route`: a refreshed LAN address, accepted only after authentication.
- `bind` / `bound`: association with the authenticated Wi-Fi session UUID.

The binary pose format remains `FPBT` version 1: state/reason, session/generation/
acquisition UUIDs, sequence and timestamps, translation, quaternion, and up to 19
bias-corrected gyro samples. Original phone clocks and source sequences remain
intact. The exact count fits the negotiated MTU after TLS overhead. Small MTUs
complete setup normally and use Wi-Fi for motion. The latest unsent pose replaces
older motion; there is no application pose FIFO.

## Background behavior and validation

Companion presence can wake the connection service. Camera permissions and cold
background camera starts retain Android's normal restrictions; the Resume tracking
notification remains available. Camera tracking stays idle until authentication
and the existing wearer/marker conditions permit it. No video is implemented.

The former bond/recovery tests were removed with that implementation. The new
protocol tests exercise real TLS records, two-sided consent, reconnect, Forget,
wrong identity, encrypted routes/motion, session binding and tampering. The Android
TLS adapter is tested with fragmented TLS 1.3 records. These checks do not replace
physical Bluetooth and Android lifecycle testing.

`frame/tests/test_bluetooth_service.py` uses a private D-Bus to check adapter
pairing readiness, service/daemon recovery, visible registration errors and
settings restoration without accessing the host radio. Run it with `dbus-daemon`
and `python3-dbus-next` installed.

Native desktop development needs `python3-dbus-next`; the packaged executable
bundles it. TLS uses the standard Python/OpenSSL and Android providers already
used by the Wi-Fi connection. No new runtime package is required.

References: [BlueZ agent](https://github.com/bluez/bluez/blob/master/doc/org.bluez.Agent.rst),
[BlueZ capabilities](https://github.com/bluez/bluez/blob/master/doc/org.bluez.AgentManager.rst),
[Python MemoryBIO](https://docs.python.org/3/library/ssl.html#memory-bio-support),
[Android SSLEngine](https://developer.android.com/reference/javax/net/ssl/SSLEngine).
