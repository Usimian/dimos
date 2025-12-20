# Dimos Mobile App

React Native mobile application (v0.0.1).

## Prerequisites

- **Node.js** >= 18
- **Xcode** (for iOS)
- **Android Studio** (for Android)
- **CocoaPods** (iOS): `sudo gem install cocoapods`

## Quick start

1. Install JS deps
   ```bash
   npm install
   ```
2. Install iOS pods (macOS only)
   ```bash
   cd ios && pod install && cd ..
   ```
3. Run the app
   - iOS: `npm run ios`
   - Android: `npm run android`

Metro bundler starts automatically; you can also run it manually with `npm start`.

## Scripts

- `npm start` – Start Metro bundler
- `npm run ios` – Run on iOS simulator/device
- `npm run android` – Run on Android emulator/device
- `npm run lint` – Run ESLint
- `npm test` – Run Jest tests

## Troubleshooting

- Reset Metro cache
  ```bash
  npx react-native start --reset-cache
  ```
- iOS: reinstall pods
  ```bash
  cd ios && rm -rf Pods && pod install && cd ..
  ```
- Android: clean build
  ```bash
  cd android && ./gradlew clean && cd ..
  ```