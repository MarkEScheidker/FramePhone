# Bluetooth companion and pose transport

Implemented for device testing; radio throughput, Frame peripheral permissions
and Android cold-start behavior still need a phone/headset run. No screen capture
or video dependency is included in this milestone.

## Setup and daily use

1. Rebuild/install both apps. Enable Bluetooth on both devices and keep them on
   the same reachable Wi-Fi LAN. Run FramePhone on Frame first.
2. On Android enter dimensions and tap Pair headset. Grant Bluetooth, notifications,
   camera and overlay permissions, then select Steam Frame in Android's companion
   picker. Location Services may need to be enabled for the system picker.
3. Approve the same six-digit number on the phone and in the FramePhone desktop
   app. Either device may be confirmed first. The BLE advertisement is named **Steam Frame**, while the app is FramePhone.
   Android waits for bond completion before MTU/services and protected reads. GATT
   characteristics require authenticated encryption; there is no Just Works
   downgrade. Connection retries keep both the OS bond and the saved app trust.
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
bond is a separate settings action. Frame stays available while its app runs; Forget phone removes its saved trust.
Android force-stop is not bypassed.

Bluetooth is the only pairing path. Both apps show Bluetooth status directly;
there is no transport selection, IP entry, LAN scan or Wi-Fi enrollment. The
phone accepts only pinned reconnect authentication on its Wi-Fi listener.
Wi-Fi failures retry automatically, including the first failed attempt. Every
screen-on/unlock while disconnected requests another authenticated route exchange,
even if the phone's address is unchanged. Both devices must already be on a
reachable Wi-Fi LAN; the app does not provision the network itself.

Camera trace collection, image copies and preview detectors stay idle without a
fresh phone marker-visible signal. After ARCore handoff, optical work sleeps
again. The already-authorized broker keeps its attachment and ring so acquisition
can resume without another authorization prompt; headset tracking is unaffected.

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
helper. While running, it registers a BlueZ DisplayYesNo default agent so incoming
phone pairing gets an actual number-comparison UI. The agent is unregistered on
shutdown; no persistent Bluetooth configuration is changed. Registration/default
agent permission failures are reported, rather than creating a weaker bond. BlueZ may deny registration or
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
file. Android retains its current verifier and a separate pending enrollment
credential until the authenticated ready response acknowledges the new trust.
Lost acknowledgments retry the same pending credential. A successful ready response
commits the new verifier atomically. Switching companion addresses drops the old
peer's verifier and proposal; Forget removes both. Changed identities/credentials
require explicit replacement approval on Frame; failed proofs never overwrite trust. While TLS
is absent, Android refreshes its LAN route and retries setup reads. Ready reads
also contain a fresh challenge so an address change can authenticate a new route
even when the previous TLS attempt failed before session creation.

After bootstrap, an encrypted read returns a fresh binding UUID and 256-bit token.
The phone binds its TLS session UUID by HMAC(token, ASCII session UUID). Frame
accepts poses only from that Bluetooth device, binding and the exact session
registered by its authenticated TLS client. TLS disconnect revokes the binding.
Challenges are consumed; incomplete control messages and client counts are bounded.
Neither private certificate keys nor Wi-Fi passwords are transferred.

## Pairing recovery

Bluetooth bond keys, Android's companion association, the phone's Keystore identity
and the application credential are separate state. Network errors never erase
any of them. Recovery is explicit when it changes which device is trusted:

| Situation | Behavior |
| --- | --- |
| Both app records and bond are valid | Reconnect automatically with a fresh challenge/session binding; no new prompt. |
| Phone manually removes its OS bond | Stop BLE/TLS and tracking; do not silently re-pair. Retry pairing starts a fresh bond flow. Saved app keys may be reused after secure bonding. |
| Authentication error after confirmation | Stop a failed security attempt with Retry connection; keep saved keys. A transport retry never starts another bond while confirmation is pending or forgets an observed completed bond. Genuine OS key loss may require system repair, but Frame's Forget is not a connection-retry step. |
| Android app reinstalled/reset, but OS bond survives | Create a new app credential; Frame offers Replace saved phone. Approval ends the old TLS/binding before using the new identity. Rejection preserves old trust. |
| Frame app record lost/reset, but phone/bond remain | Phone proposes a fresh credential over encrypted BLE. Frame asks Connect this phone; no OS unpair is required. |
| Frame explicitly forgets a phone | Clear trust, old binding, pending requests and recent bond approval. The existing OS bond cannot silently re-enroll; reconnect needs confirmation. |
| Both records exist but credentials differ | Return a specific app-trust mismatch, then offer a fresh verified credential proposal and confirmation. Do not mislabel this as an OS encryption failure. |
| App stops or an acknowledgment is lost during enrollment | Retain the same pending proposal across restart; a repeated valid proof completes without replacing a newer record or prompting twice. |
| Transport disconnect during number comparison | Keep the same pending number; it is a bond transaction, not a GATT connection. Only BlueZ Agent.Cancel/Release, explicit rejection, shutdown or timeout cancels it. Both acceptance orders are valid. |
| App trust proposal disconnects, or an approval is rejected/times out | Cancel that proposal and preserve prior trust. Retry connection resumes using saved keys without silently replacing them. |
| Another phone tries pairing while a prompt is open | Reject the second request; it cannot replace the device/number being confirmed. |
| Saved trust changes while confirmation is open | Reject the stale approval instead of overwriting the newer record. |
| User switches to another companion address | Drop the old peer's pending secret/verifier and close its active connection. Never share a pending credential between headsets. |
| Wi-Fi changes address, drops, or is unavailable | Keep Bluetooth/app trust and retry routes/TLS with bounded backoff, including on screen-on/unlock. |
| MTU is too small for motion packets | Complete Bluetooth setup; use Wi-Fi for motion automatically. |

Initial app enrollment can reuse a just-approved number comparison for two minutes,
for that device only. An existing OS bond without an app record needs explicit
Connect confirmation. This prevents Forget being immediately undone by background
reconnection. Application proposals are verified before prompting, and stored
identity is checked again after approval. No saved trust is replaced by a rejected, expired,
replayed or stale request. Pending secrets, tokens and comparison numbers are not
written to diagnostics.

The app uses supported Android bond APIs; it does not remove bonds by reflection
or discard other Bluetooth devices. Android force-stop/permission revocation and
host Bluetooth policy still require user action. Hardware trials remain necessary
for actual OS bonding, privacy-address resolution and radio interruption behavior.

Android uses reported bond-state broadcasts rather than re-reading a potentially
lagging cached getter. It retains the in-progress bond across GATT disconnects;
no second createBond call is allowed while waiting. Duplicate callbacks cannot
restart setup, and an observed completed bond survives ordinary transport retries.
After bonding, a 1.6-second settling interval allows encryption/service-change
processing before discovery; this follows the ordering described by
[Nordic's BLE manager](https://github.com/NordicSemiconductor/Android-BLE-Library/blob/main/ble/src/main/java/no/nordicsemi/android/ble/BleManager.java).
Discovery precedes MTU optimization. Unsolicited MTU/discovery callbacks cannot
advance setup during bonding; optional MTU timeout falls back to small-packet
bootstrap rather than disconnecting a valid bond. Connection/PHY optimization
happens after binding. Details retains the last failure stage until setup succeeds.
These changes affect connection setup, not steady-state pose cadence.

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
the base pose, so setup completes over Bluetooth and Wi-Fi carries motion. One GATT operation can be
in flight and only the latest unsent pose is retained; old motion never forms
an application FIFO. Small MTUs still support secure bootstrap through bounded
fragments and consistent long-read snapshots; pose traffic automatically stays on
Wi-Fi when the negotiated MTU cannot carry a base pose. BLE reads its source independently of the Wi-Fi writer,
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

References: [Android GATT status codes](https://android.googlesource.com/platform/packages/modules/Bluetooth/+/refs/heads/main/system/stack/include/gatt_api.h),
[Android asynchronous bonding](https://developer.android.com/reference/android/bluetooth/BluetoothDevice#createBond()),
[BlueZ pairing agent](https://bluez.readthedocs.io/en/latest/agent-api/),
[companion pairing](https://developer.android.com/develop/connectivity/bluetooth/companion-device-pairing),
[background BLE](https://developer.android.com/develop/connectivity/bluetooth/ble/background),
[foreground/camera restrictions](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start),
[BlueZ GATT](https://bluez.readthedocs.io/en/latest/gatt-api/),
[BlueZ advertising](https://bluez.readthedocs.io/en/latest/advertising-api/).
