# Install PrePro for iPhone (test builds, free)

PrePro for iPhone isn't on the App Store yet. Test builds are installed with **SideStore** and **your own free Apple
ID**: no payment, no Mac. You need a computer (Windows or Mac) once, for about 15 minutes. After that, everything
happens on the iPhone.

**You need:** an iPhone on iOS 26 (iPhone 17 Pro or iPhone 17 for testing), a passcode set on it, an Apple ID (a free
one is fine), Wi-Fi, a cable, and a Windows PC or a Mac for the first setup.

## 1. One-time setup (about 15 minutes)
1. **On the iPhone:** install **LocalDevVPN** from the App Store (free). SideStore uses it to install and refresh
   apps on the phone itself.
2. **On the computer:**
   - Windows: install **iTunes from apple.com**, not the Microsoft Store version.
   - Download **iLoader**, SideStore's installer, only from its official page:
     <https://github.com/nab138/iloader/releases> (or iloader.app).
3. Connect the iPhone with the cable, unlock it and tap **Trust This Computer**.
4. Open iLoader and sign in with your Apple ID. It goes to Apple only; PrePro never sees it. Choose **Install
   SideStore**. iLoader also puts the pairing file SideStore needs on the phone.
5. **On the iPhone:**
   - Settings → General → **VPN & Device Management** → trust the profile with your Apple ID.
   - Settings → Privacy & Security → **Developer Mode** → On. The phone restarts; confirm when it asks.
6. Open **LocalDevVPN** and tap **Connect** (allow the VPN). Open **SideStore** and sign in with the same Apple ID.

## 2. Install PrePro
1. On the iPhone, open this page in Safari: <https://github.com/buildcool/PrePro/releases/tag/ios-nightly>
2. Tap **PrePro.ipa** to download it.
3. In **SideStore**: My Apps → **+** → choose **PrePro.ipa** from Downloads. Keep LocalDevVPN connected while it
   installs.

**A new build:** do the same again. It replaces the old one and keeps your settings. The build number is on PrePro's
first screen.

## 3. Every 7 days
A free Apple ID's apps stop opening after 7 days unless they're refreshed. Once a week, connect LocalDevVPN, open
SideStore and tap **Refresh All**. A free Apple ID can have at most 3 apps installed this way.

## 4. Testing a build
1. Open PrePro and note the **build number** on the first screen.
2. Do the steps for that build (below, or what the person who sent it asks).
3. Tap **Send test report** and send it back (WhatsApp, mail…). The report has the build, the phone model, its iOS
   version and the times PrePro read. **No photos or videos** are in it. Add a screen recording or an exported video
   only if you're asked to.

### What to test in the first builds (M0)
1. **Apple Intelligence** on the first screen should say **Ready** (if Apple Intelligence is on in Settings).
2. **Choose clips from one day:** pick 6–15 videos and photos you shot today or on one day.
   - Each time PrePro shows ("6:42 am") must match when you shot it. Check two of them in Photos: swipe up on a clip
     to see its time.
   - The summary line shows the day, how many clips, and the first and last time.
3. **Send test report.**

### What to test next (M1: a photo reel)
1. Put a song on the phone first (an .mp3 or .m4a in the Files app: AirDrop or save one from mail). Songs from Apple
   Music can't be read.
2. **Make a photo reel:** tap **Choose photos** and pick 10–25 photos of one day or one trip, with a few near-identical
   shots, one blurry and one dark one if you have them. Tap **Choose a song** and pick the song. Tap **Make the reel**.
   - It should finish within about a minute and show a cover with a title like "Goa · Oct 2026".
   - The photos below the cover should be in the order you took them, after the cover.
   - Under **What PrePro decided**: the near-identical shot, the blurry and the dark photo should be left out, each
     with its reason. Note any photo it left out that you'd have kept, or kept that you'd have cut.
3. **Send test report.** It now also lists the reel's decisions in words (its title too); still no photos, videos or
   file names.

## If something goes wrong
- **"Untrusted Developer" / it won't open:** trust the profile (step 1.5).
- **"Developer Mode required":** turn it on (step 1.5).
- **Install or refresh fails:** connect LocalDevVPN first, then try again in SideStore.
- **"Maximum number of apps":** remove another sideloaded app in SideStore (3 at most with a free Apple ID).
- **The app stopped opening:** it wasn't refreshed for 7 days. Refresh All in SideStore.
- **Fallback:** AltStore with AltServer on a PC (<https://altstore.io>) does the same job.

Privacy: PrePro edits on the phone; your footage never leaves it. Your Apple ID goes only to Apple, through iLoader
and SideStore.
