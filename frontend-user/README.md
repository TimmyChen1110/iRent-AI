# iRent User iOS App

This folder contains the iOS 18+ SwiftUI source for the offline rental flow.

## Add it to Xcode

The repository did not contain an iOS app target. Create an iOS App target named
`iRentUserApp`, then add all Swift files under `iRentUserApp/` to that target.

Set the deployment target to iOS 18 and add this privacy usage description:

- `NSCameraUsageDescription`: 「用於拍攝取車與還車車況照片。」

The system `PhotosPicker` needs no blanket photo-library permission.

## Generate the offline models

The converter requires a separate macOS Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install ultralytics torch torchvision coremltools onnx onnx2torch
python 環節一_拍攝即時防呆/app_models/scripts/export_coreml.py
```

Add the resulting model packages in `iRentUserApp/Models/` to the app target:

- `PlateDetector.mlpackage`
- `PlateOCR.mlpackage`
- `ViewClassifier.mlpackage`

The app never sends an image to a server-side model. If any local model is absent,
the capture screen reports the missing model and rejects the photo.

## Local API

Start the existing backend application, then set its reachable LAN URL in the app
settings. The new `POST /v1/mobile-inspections/photos` endpoint stores only
on-device-passed evidence and validates stage, angle, rental plate, image hash,
and duplicate submission. It does not import any ML runtime.
