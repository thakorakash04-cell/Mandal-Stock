# Mandal Stock Android v3.0 — existing setup

The app has native Android screens for stock, members, history and admin forms. It uses the existing Mandal Stock Streamlit deployment, PostgreSQL database and admin credentials. No Oracle, separate API, Docker server, new secret or extra hosting account is required.

## Install
1. Update the existing GitHub repository/deployment with the app.py, native_protocol.py and native_bridge/ files supplied in this release. The ordinary website layout stays the same.
2. Install Mandal-Stock-v3.0.apk over v1/v2. The package and signing key are unchanged.
3. Enter the HTTPS address of your existing Mandal Stock Streamlit website. Do not enter the GitHub repository URL. A v1 saved website address is reused automatically; the discarded v2 API setting is not reused.
4. Use Stock, Holders, History and Admin. Sign in with the same existing admin username/password. All devices and the website read/write the same server database.

No database URL, database password or admin password is embedded in the APK. Existing Streamlit Secrets stay on the existing host. If Streamlit has put the app to sleep, open the ordinary website once to wake it, then tap Refresh in the APK. The existing deployment must be reachable without hosting-level external sign-in; the website's own admin screen remains protected as before.

## How the existing setup is reused
Android draws all visible controls with native widgets. A small, invisible WebView carries only the existing Streamlit component connection and its session. It loads the dedicated data-only component via `?mandal_native=1`, never the website's inventory layout. This transport is needed because Streamlit does not expose a REST API. No new HTTP listener or unsupported Streamlit server modification is used. It still needs a working Android System WebView and internet.

The app retains the existing server controller for permission checks, login throttling, stock validation, photos and Gujarati messages. The standard website continues to use its original frontend. Website metadata is cached for up to 30 seconds; use Refresh to see changes sooner. Native Refresh invalidates the shared metadata cache. No additional polling job is added.

## Included mobile functions
- Bottom navigation: Stock, Holders, History, Admin.
- Stock cards with totals, search, category and availability filters; item photo and holder details.
- Admin item creation, category, initial quantity, notes and photo selection/replacement.
- Member add/edit/pause with admin-only WhatsApp numbers; public member holdings and copy/share lists.
- Handovers and partial/full returns with available/held quantities and notes.
- History search, type filtering, pagination, Gujarati return confirmations and CSV export via Android's save dialog.
- Explicit recovery of interrupted handover/return requests. The original operation UUID is retained locally, and the database records the operation at most once.

Photos are resized to at most 720 px and 60 KB on the phone before transfer, with EXIF orientation applied and metadata stripped; server compression/validation still applies. Only versioned photos are cached on the phone (about 10 MB). Credentials and member/phone lists are not persisted locally. WhatsApp sharing still opens the messaging app for the person to press Send.

If a handover or return loses connection, go to Admin → Review unfinished stock update after reconnecting/signing in. Retrying keeps the same operation UUID. Do not discard it until history has been checked. An interrupted add-item/member/photo operation should be checked in the refreshed register before re-entry. Offline stock editing, background sync and push notifications are not included.

## Rebuild
Requires a JDK, Android API 34 platform and Android build tools. From android/:

```bash
export ANDROID_PLATFORM=/path/to/platforms/android-34
export ANDROID_BUILD_TOOLS=/path/to/build-tools/34.0.0
export KEYSTORE=/private/path/mandal-stock.jks
export KEY_ALIAS=mandalstock
read -r -s -p 'Keystore password: ' KEYSTORE_PASSWORD
export KEYSTORE_PASSWORD
bash build.sh
```

Output: android/deliverables/Mandal-Stock-v3.0.apk. Android 8+ is supported. Future updates need a higher versionCode and the same signing key. The private download bundle contains signing-private/ for future updates. Never push that folder or the complete private bundle to public GitHub. Only the source/ subtree belongs in the repository.

## Validation
The native APK compiles against Android API 34; v2/v3 signatures and its signing-key match with v1/v2 were verified. Server tests cover admin guards, public phone privacy, duplicate deliveries, durable ledger retries, altered-payload rejection, partial/over-returns, history, expired sessions and logout, in addition to the existing website/store/media tests. Streamlit AppTest exercises the actual native component event bridge and the ordinary website. JavaScript transport checks cover render messages, origin/source checks, duplicate deliveries and credential acknowledgements. Browser/Android runtime testing remains pending. No physical Android device or production deployment URL was available for end-to-end device testing.
