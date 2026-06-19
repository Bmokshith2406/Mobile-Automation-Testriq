Yes, I checked [Sample_Appium.py](D:/Demo-Ready-TW.2324/Executor-Regenrator/Sample_Appium.py). It is an Appium Clock test and can be run through Executor-Regenerator Swagger.

**Before Swagger**
Start Executor-Regenerator:

```powershell
cd D:\Demo-Ready-TW.2324\Executor-Regenrator
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

Open Swagger:

```text
http://127.0.0.1:8000/docs
```

Click **Authorize** and enter:

```text
ExecutorRegenerator
```

That goes into header `X-API-KEY`.

**Swagger Run Steps**
In Swagger, open:

```text
POST /executor/run
```

Click **Try it out**.

Fill fields exactly like this:

```text
script:
D:\Demo-Ready-TW.2324\Executor-Regenrator\Sample_Appium.py
```

```text
appium_server_url:
http://34.46.45.187:4723/wd/hub
```

```text
appium_device_filter:
leave blank
```

For `appium_device_matrix`, paste this JSON:

```json
{
  "devices": [
    {
      "label": "Pixel 7 Local GCP",
      "slug": "pixel_7_local_gcp",
      "device_name": "Pixel_7_API_36",
      "platform_name": "Android",
      "udid": "emulator-5554",
      "app_package": "com.google.android.deskclock",
      "app_activity": "com.android.deskclock.DeskClock",
      "app_wait_activity": "*",
      "no_reset": true,
      "relaunch_before_test": true,
      "relaunch_before_step_retry": true
    }
  ]
}
```

Then click **Execute**.

**Important**
Your `.env` already has:

```env
APPIUM_SERVER_URL=http://34.46.45.187:4723/wd/hub
```

So technically you can leave `appium_server_url` blank in Swagger, but I recommend filling it for this first run so there is no doubt.

Curl equivalent:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/executor/run" `
  -H "X-API-KEY: ExecutorRegenerator" `
  -F "script=@D:\Demo-Ready-TW.2324\Executor-Regenrator\Sample_Appium.py" `
  -F "appium_server_url=http://34.46.45.187:4723/wd/hub" `
  -F "appium_device_matrix={""devices"":[{""label"":""Pixel 7 Local GCP"",""slug"":""pixel_7_local_gcp"",""device_name"":""Pixel_7_API_36"",""platform_name"":""Android"",""udid"":""emulator-5554"",""app_package"":""com.google.android.deskclock"",""app_activity"":""com.android.deskclock.DeskClock"",""app_wait_activity"":""*"",""no_reset"":true,""relaunch_before_test"":true,""relaunch_before_step_retry"":true}]}"
```

You should get a JSON response with execution status and artifacts/zip path.