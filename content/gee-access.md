+++
title = "Our Research Group's Google Earth Engine Project Access"
description = 'A guide for our research group members requesting access to the shared Earth Engine project.'
draft = false
[params]
hideMeta = true
+++

Our research group maintains a shared Google Earth Engine (GEE) Cloud Project with Partner Tier access to support computationally intensive, noncommercial academic research.

Eligible group members may request permission to use this project through their own Google accounts. Access is managed by the student project coordinator.

Please follow the instructions below to request access and get started.

## 1. Before You Apply

Please make sure that:

- You are a member of our research group.
- You have a Google account that you intend to use with Earth Engine.
- You understand what computing resources or project assets your research requires.
- Your intended work is for noncommercial academic research consistent with the project's approved use.

You do not need to create another Partner Tier project or share anyone else's Google account.

## 2. How to Request Access

Contact the student project coordinator through our research group's usual communication channel.

Please provide the following information:

- **Name:** Your full name.
- **Google Account:** The email address associated with the Google account you will use for Earth Engine.
- **Research Purpose:** A brief description of your research or computational task.
- **Requested Access:** Indicate whether you need to run computations and export results, access project assets, or both.
- **Expected Workload:** An approximate description of the scale and frequency of your tasks, especially if you plan to run large or long-running jobs.

The coordinator will review your request and arrange the appropriate permissions when approved.

Please do not share your Google password, API keys, authentication tokens, or other account credentials.

## 3. After Your Access Is Approved

Once the coordinator confirms that your access has been granted, you can start using the shared project with your own Google account.

### Option A: Earth Engine Code Editor

1. Open the [Google Earth Engine Code Editor](https://code.earthengine.google.com/).
2. Sign in using the same Google account that you provided in your access request.
3. Click the account/profile menu in the upper-right corner.
4. Select **Change Cloud Project**.
5. Find and select our research group's shared Cloud Project. The project identifier will be provided to you after approval.
6. Confirm that the shared project is selected.
7. Start with a small test computation before submitting resource-intensive tasks.

If the project does not appear in the selection list, confirm that you are signed in with the correct Google account and contact the coordinator.

### Option B: Python API

If you use Earth Engine through Python, authenticate using your own Google account and specify the approved Cloud Project when initializing Earth Engine.

For example:

```python
import ee

ee.Authenticate()
ee.Initialize(project="YOUR_PROJECT_ID")
```

Replace `YOUR_PROJECT_ID` with the project ID provided by the coordinator.

Authentication normally needs to be completed when required by your environment; it is not necessary to repeat interactive authentication before every computation if valid credentials are already available.

## 4. Responsible Use of Shared Resources

The Partner Tier allocation is a shared research group resource, not a separate quota assigned to each individual member.

Please follow these guidelines:

- Use the shared project only for approved noncommercial research activities.
- Coordinate large-scale or long-running computational tasks with the student project coordinator.
- Avoid unnecessary duplicate exports and excessive resource consumption.
- Do not share project access with unauthorized individuals.
- Do not modify or delete shared assets unless you have explicit authorization.
- Notify the coordinator if your research needs or required permissions change.
- Follow all applicable Google Earth Engine policies and our research group's resource management arrangements.

Access permissions may be adjusted or revoked when necessary to protect the shared project and ensure fair resource use.

## 5. Troubleshooting

If you encounter an access-related issue:

1. Check that you are signed in with the Google account you submitted.
2. Verify that the correct Cloud Project is selected.
3. Check whether your requested access has been confirmed.
4. Contact the coordinator with a short description of the problem and the relevant error message.

Do not send passwords, tokens, or other sensitive credentials when requesting technical support.

For any other questions or unresolved issues, please contact [chutj@foxmail.com](mailto:chutj@foxmail.com).

## Official Documentation

- [Earth Engine Access](https://developers.google.com/earth-engine/guides/access)
- [Control Access to Earth Engine Resources](https://developers.google.com/earth-engine/guides/access_control)
- [Earth Engine Code Editor Quickstart](https://developers.google.com/earth-engine/guides/quickstart_javascript)
- [Earth Engine Noncommercial Tiers](https://developers.google.com/earth-engine/guides/noncommercial_tiers)
