# Single Click Stream - setup

This app shares your screen and the sound of your computer live on YouTube.

## What is in this folder

- `streamer.py` - the app.
- `panel.html` - the control panel page.
- `settings.json` - the settings (title, privacy, quality). The app makes this file.
- `client_secret.json` - your Google key file. You must add this file (see part 1).
- `token.json` - your sign-in. The app makes this file. Do not give it to other persons.
- `logs\` - the log files. Look here if a problem occurs.
- `create_shortcuts.ps1` - makes the desktop shortcuts again.

## Part 1 - Get the Google key file (one time only, approximately 10 minutes)

1. Go to https://console.cloud.google.com/ and sign in with the Google account of your YouTube channel.
2. At the top, click the project list. Click "New project". Type the name "Single Click Stream". Click "Create".
3. Make sure that the new project is selected at the top.
4. Go to "APIs & Services" > "Library". Find "YouTube Data API v3". Click it. Click "Enable".
5. Go to "Google Auth Platform" (also named "OAuth consent screen"). Click "Get started".
6. Type an app name (for example "Single Click Stream"). Select your e-mail address. Click "Next".
7. For "Audience", select "External". Click "Next". Type your e-mail address. Click "Next". Accept the policy. Click "Create".
8. Go to "Audience". Under "Test users", click "Add users". Type your Google e-mail address. Click "Save".
9. Go to "Clients". Click "Create client". For "Application type", select "Desktop app". Click "Create".
10. Click "Download JSON". Save the file in this folder with the name `client_secret.json`.

CAUTION: When the app stays in "Testing" mode, Google stops your sign-in after 7 days. Then the app asks you to sign in again. To stop this, publish the app:

1. Go to "Branding". Fill in only these fields:
   - "App name": Single Click Stream
   - "User support email": your e-mail address
   - "Developer contact information": your e-mail address
2. Do not add an app logo. CAUTION: A logo makes Google review the app before it can be used. This review takes weeks.
3. Fill in the "App domain" fields:
   - "Application home page": the address of `docs/index.html` on your GitHub Pages (for this project: https://johannesleung.com/single-click-stream/)
   - "Application privacy policy link": the address of `docs/privacy.html` (for this project: https://johannesleung.com/single-click-stream/privacy.html)
   - "Terms of service": keep empty.
   - "Authorized domains": the domain of these pages (for this project: johannesleung.com)
   The pages are in the GitHub repository watchowski/single-click-stream (folder "docs").
4. Click "Save".
5. Go to "Audience" and click "Publish app". Click "Confirm". Google then shows a warning page at sign-in ("Google has not verified this app"). Click "Advanced" and then "Go to Single Click Stream". This is safe because it is your own app.

## Part 2 - Make sure that your channel can stream live

1. Go to https://www.youtube.com/features.
2. Make sure that "Live streaming" shows "Enabled".
3. If it is not enabled, click "Enable". YouTube needs up to 24 hours to enable it the first time.

## Part 3 - Sign in (one time only)

1. Double-click the desktop shortcut "Stream Control Panel".
2. The control panel opens in your web browser.
3. Click "Sign in with Google". Select your YouTube account. Allow access.

## Daily use

- To start a stream: double-click "Go Live on YouTube" on the desktop. Or pin it to the taskbar for one click.
  - The app makes a new stream, starts to send your screen and sound, and copies the link to the clipboard.
  - The control panel opens and shows the link. YouTube shows the stream after approximately 10 to 30 seconds.
- To change the title or the privacy (Public, Unlisted, Private): type the new value in the control panel and click "Save". You can do this during the stream.
- To change the sound level for the viewers: move the "Stream volume" slider (0% to 200%). Click "Mute stream" to send no sound. Click "Unmute stream" to go back to the earlier level. Your own volume does not change.
- To stop the stream: click "Stop stream". The recording stays on your channel.
- To delete a stream: click "Delete". This removes the stream and its recording from YouTube.
- To set the title and privacy for the next single-click start: use "Settings for the next stream".

Privacy values:
- Public: all persons can find and watch the stream.
- Unlisted: only persons with the link can watch. This is the default value.
- Private: only you, and persons that you invite in YouTube Studio, can watch.

## Settings (settings.json)

- `monitor`: the screen to share. 0 is the first screen, 1 is the second screen.
- `framerate`: frames per second (30 is good).
- `max_height`: the maximum picture height (1080 or 720). Use 720 if your internet is slow.
- `video_bitrate_kbps`: the video quality. 4500 for 1080p, 2500 for 720p.
- `encoder`: `libx264` (works on all computers). Use `h264_nvenc` for an NVIDIA graphics card to decrease the load on the computer.
- `capture_audio`: `true` sends the computer sound. `false` sends silence.
- `hdr_mode`: `auto` corrects the colors when the screen uses Windows HDR. `off` stops the correction.
- `video_source`, `audio_source`: set these in the control panel ("What to share").
- `copy_link_on_start`, `open_panel_on_start`: `true` or `false`.

## If a problem occurs

- Look at `logs\app.log` and `logs\ffmpeg.log`.
- To test the screen and sound capture without YouTube, run this command in this folder:
  `python streamer.py --test-capture test.mp4`
  The app records 8 seconds to the file `test.mp4`.
- By default, the app uses the sound of your default speakers. Your microphone is not included.
- To send the sound of only one app (for example a game), select it under "Sound of one app" in "What to share". The app must be open. Some games mute their sound when they are not the active window. Change this in the sound settings of the game.
- The app uses the YouTube API. Each new stream uses approximately 200 of the 10,000 free daily units. This is sufficient for many streams each day.
