# Bluetooth companion and pose transport

Implemented for device testing; radio throughput, Frame peripheral permissions
and Android cold-start behavior still need a phone/headset run. No screen capture
or video dependency is included in this milestone.

## Setup and daily use

1. Rebuild/install both apps. Enable Bluetooth on both devices and keep them on
   the same reachable Wi-Fi LAN. Run FramePhone on Frame first.
2. On Android enter dimensions and tap Connect. Grant Bluetooth, notifications,
   camera and overlay permissions, then select FramePhone in Android's companion
   picker. Location Services may need to be enabled for the system picker.
3. Approve the Bluetooth numeric-comparison/bond prompt on both devices. GATT
   characteristics require authenticated encryption; there is no Just Works
   downgrade. An existing weaker bond may need removing in Bluetooth settings.
4. Bluetooth transfers the application trust information and current LAN route.
   Frame verifies the phone's complete saved certificate pin before sending a
   Wi-Fi credential. It then connects automatically; no IP entry is needed.
5. A previous Wi-Fi pairing migrates using its existing credential verifier.
   New pairing establishes the credential over the approved Bluetooth bond.
6. On later runs, the Frame app advertises; Android's companion presence service
   can wake the connection service while the setup activity stays closed.
   Camera tracking resumes automatically when the existing camera service is
   still available. If Android blocks a cold background camera start, tap the
   Resume tracking notification action. This action does not open the setup UI.

Disconnect on Android disables background reconnection until Connect is used
again. Forget also removes the companion association; removing the OS Bluetooth
bond is a separate settings action. Frame Disconnect suppresses automatic route
hints until Reconnect/Connect is used. Android force-stop is not bypassed.

An explicitly requested Wi-Fi fallback remains in Android Details → Connect using
Wi-Fi and Frame Connection → Use Wi-Fi. Legacy Wi-Fi enrollment still requires
physical fingerprint comparison. Bluetooth-paired records wait for Bluetooth at
startup rather than using broadcast LAN discovery as their normal bootstrap.

## Responsibilities

| Path | Content |
| --- | --- |
| Authenticated BLE setup characteristic | First application credential/public certificate pin, verifier proof, LAN route, session binding. |
| BLE pose characteristic | Latest ARCore position/orientation/state plus bounded bias-corrected gyro history. |
| Pinned TLS on Wi-Fi | Reliable session/marker/wearer control, four-timestamp clock probes, raw sensor diagnostics and backup poses. |
| Future Wi-Fi video | Separate capture/encoding/streaming work; not implemented. |

The current session still needs Wi-Fi for control and clock mapping. Once BLE
binds, Wi-Fi pose traffic reduces to 5 Hz plus state changes as a backup; if BLE
is not bound, Wi-Fi retains its original rate. Frame selects BLE while its last
valid receipt is at most 150 ms old and Wi-Fi has no newer phone timestamp;
otherwise it selects the Wi-Fi pose mailbox. Both paths
retain original phone timestamps and use the same verified phone clock epoch.
The dashboard identifies the selected pose transport. Radio delay must be measured;
BLE is not assumed to outperform Wi-Fi, and changing transport does not remove
the renderer's intentional smoothing delay.

## Trust and key exchange

The host uses the existing BlueZ daemon through system D-Bus. It registers a
local LE GATT service and advertisement as the desktop user; it does not install
another daemon, change adapter power, alter D-Bus policy or require a root radio
helper. A host agent handles Bluetooth pairing. BlueZ may deny registration or
lack peripheral/advertising support; that is a visible setup failure.

Sensitive characteristics require encrypt-authenticated-read/write flags. The
application also rejects direct D-Bus reads/writes whose sender is not the current
BlueZ daemon owner, so local callers cannot fake a radio device option.

The setup read returns a fresh, per-device, 15-second challenge and the adapter
identity address. The phone writes its public certificate SHA-256 pin, IPv4 route,
challenge and an HMAC proof. The canonical ASCII transcript is:

```
framephone-bt-bootstrap-v1\nCHALLENGE\nUPPERCASE_ADAPTER_ADDRESS\nPIN\nIPV4\n47643\n
```

The HMAC key is SHA-256 of the existing ASCII reconnect credential. Android already
stores this verifier, so migration does not require recovering the original
credential on the phone. New enrollment generates a 256-bit credential and sends
it only through authenticated BLE; Frame saves it in its existing private pairing
file. Android removes the pending enrollment secret after the write is acknowledged.
Existing pins or credentials are never overwritten by a failed proof. While TLS
is absent, Android refreshes its LAN route and retries setup reads. Ready reads
also contain a fresh challenge so an address change can authenticate a new route
even when the previous TLS attempt failed before session creation.

After bootstrap, an encrypted read returns a fresh binding UUID and 256-bit token.
The phone binds its TLS session UUID by HMAC(token, ASCII session UUID). Frame
accepts poses only from that Bluetooth device, binding and the exact session
registered by its authenticated TLS client. TLS disconnect revokes the binding.
Challenges are consumed; incomplete control messages and client counts are bounded.
Neither private certificate keys nor Wi-Fi passwords are transferred.

## Wire format

Service UUID: `f7a10001-81a6-4c44-9c79-99ac54174901`.
Setup characteristic ends `0002`, pose characteristic ends `0003`, with the same
remaining UUID suffix. Setup supports acknowledged read/write; poses use write
without response. JSON setup messages are at most 1024 bytes. Each application
fragment starts with little-endian uint16 message ID, offset and total size;
fragments must arrive in order and expire after three seconds.

Pose header is 116 bytes. Integers/floats are little endian; UUIDs are canonical
RFC 4122 byte order:

| Field | Bytes |
| --- | ---: |
| Magic FPBT, version, flags, state/reason, gyro count | 8 |
| Connection session, anchor generation, acquisition UUIDs | 48 |
| Sequence, update time, original ARCore frame time, optional capture time | 32 |
| Translation xyz and quaternion xyzw, float32 | 28 |
| Each gyro sample: phone time uint64, corrected xyz float32 | 20 |

Flag bit 0 is marker-required; bit 1 validates capture time. State low nibble is
tracking/paused/error/stopped (0–3). Reason high nibble is empty/headset-not-worn/
user-dismissed/screen-locked/camera-in-use (0–4). Unknown detailed ARCore failure
text remains on the reliable diagnostic path. Up to 19 gyro samples fit a packet.
Reserved bits, malformed UUID/session data, nonfinite transforms, reordered
poses and invalid timestamps are rejected. Raw phone sensor recording is retained.
Pose evidence records identify Bluetooth/Wi-Fi transport; backup traffic can contain
the same sequence on both paths.

Android requests MTU 517, high connection priority and 2M PHY. These are requests;
the negotiated MTU determines packet size. An MTU smaller than 119 cannot carry
the base pose and leaves the Wi-Fi path available. One GATT operation can be
in flight and only the latest unsent pose is retained; old motion never forms
an application FIFO. BLE reads its source independently of the Wi-Fi writer,
so a blocked Wi-Fi send cannot hold up Bluetooth pose submission. Pose writes timing out after 300 ms reconnect, and retry
backoff caps at five seconds. Frame also re-registers after adapter/daemon release.

## Background limitations and tests

Companion association/presence can start the connected-device foreground service;
it does not automatically grant camera access from a cold background process.
The camera start is attempted and platform rejection produces an actionable
notification. Camera service permissions and MediaProjection consent are separate.
No hidden activity, accessibility service, root workaround or permission bypass
is used. Test screen-off/unlock, Home, process recreation and force-stop explicitly.

Tests cover cross-language wire bytes, authenticated enrollment and migration,
wrong proof/pin/session/device rejection, fragmentation bounds, freshness fallback,
and actual service/advertisement registration on a private D-Bus with simulated
BlueZ. This does not validate Bluetooth controller behavior or Android presence.
Native development needs python3-dbus-next; the executable bundles Ubuntu's package
and its license. CI tests use a private dbus-daemon, never the host BlueZ service.

References: [companion pairing](https://developer.android.com/develop/connectivity/bluetooth/companion-device-pairing),
[background BLE](https://developer.android.com/develop/connectivity/bluetooth/ble/background),
[foreground/camera restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start),
[BlueZ GATT](https://bluez.readthedocs.io/en/latest/gatt-api/),
[BlueZ advertising](https://bluez.readthedocs.io/en/latest/advertising-api/).
