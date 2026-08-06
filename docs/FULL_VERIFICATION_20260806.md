# Full verification

```json
{
  "results": {
    "smoke_getMe": true,
    "smoke_all_load": true,
    "logic_helpers": true,
    "pytest_subset": false,
    "pytest_out": "......................F...................................               [100%]\n=================================== FAILURES ===================================\nE   AssertionError: assert ('Enter a NIFTY level (e.g. 24160).' is None)\n/home/ubuntu/rahul_Changes/tests/test_buffer_config.py:144: AssertionError: assert ('Enter a NIFTY level (e.g. 24160).' is None)\n=========================== short test summary info ============================\nFAILED tests/test_buffer_config.py::test_nifty_level_roundtrip_pe - Assertion...\n",
    "bot_starts": {
      "drishti": {
        "status": "FAIL",
        "alive_at_12s": true,
        "has_bad": true,
        "log": "/home/ubuntu/Trading_Runtime_Rahul/Logs/uat/smoke_start_drishti.log",
        "tail": "_post(\n           ^^^^^^^^^^^^^^^^^^^^^^^\n    ...<6 lines>...\n    )\n    ^\n  File \"/home/ubuntu/rahul_Changes/.venv/lib/python3.14/site-packages/telegram/_bot.py\", line 741, in _do_post\n    result = await request.post(\n             ^^^^^^^^^^^^^^^^^^^\n    ...<6 lines>...\n    )\n    ^\n  File \"/home/ubuntu/rahul_Changes/.venv/lib/python3.14/site-packages/telegram/request/_baserequest.py\", line 198, in post\n    result = await self._request_wrapper(\n             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n    ...<7 lines>...\n    )\n    ^\n  File \"/home/ubuntu/rahul_Changes/.venv/lib/python3.14/site-packages/telegram/request/_baserequest.py\", line 375, in _request_wrapper\n    raise exception\ntelegram.error.Conflict: Conflict: terminated by other getUpdates request; make sure that only one bot instance is running\n"
      },
      "kavach": {
        "status": "PASS",
        "alive_at_12s": true,
        "has_bad": false,
        "log": "/home/ubuntu/Trading_Runtime_Rahul/Logs/uat/smoke_start_kavach.log",
        "tail": "2026-08-06 14:13:42,354 INFO batman.kavach: KAVACH: event subscriptions registered \u2713\n2026-08-06 14:13:42,354 INFO batman.kavach: KAVACH bot application built \u2713\n2026-08-06 14:13:42,761 INFO httpx: HTTP Request: POST https://api.telegram.org/bot***REDACTED***/getMe \"HTTP/1.1 200 OK\"\n2026-08-06 14:13:42,762 INFO batman.kavach: KAVACH event loop bound for EventBus dispatch\n2026-08-06 14:13:42,896 INFO httpx: HTTP Request: POST https://api.telegram.org/bot***REDACTED***/deleteWebhook \"HTTP/1.1 200 OK\"\n2026-08-06 14:13:42,898 INFO telegram.ext.Application: Application started\n2026-08-06 14:13:53,303 INFO httpx: HTTP Request: POST https://api.telegram.org/bot***REDACTED***/getUpdates \"HTTP/1.1 200 OK\"\n"
      },
      "jagran": {
        "status": "FAIL",
        "alive_at_12s": true,
        "has_bad": true,
        "log": "/home/ubuntu/Trading_Runtime_Rahul/Logs/uat/smoke_start_jagran.log",
        "tail": "_post(\n           ^^^^^^^^^^^^^^^^^^^^^^^\n    ...<6 lines>...\n    )\n    ^\n  File \"/home/ubuntu/rahul_Changes/.venv/lib/python3.14/site-packages/telegram/_bot.py\", line 741, in _do_post\n    result = await request.post(\n             ^^^^^^^^^^^^^^^^^^^\n    ...<6 lines>...\n    )\n    ^\n  File \"/home/ubuntu/rahul_Changes/.venv/lib/python3.14/site-packages/telegram/request/_baserequest.py\", line 198, in post\n    result = await self._request_wrapper(\n             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n    ...<7 lines>...\n    )\n    ^\n  File \"/home/ubuntu/rahul_Changes/.venv/lib/python3.14/site-packages/telegram/request/_baserequest.py\", line 375, in _request_wrapper\n    raise exception\ntelegram.error.Conflict: Conflict: terminated by other getUpdates request; make sure that only one bot instance is running\n"
      },
      "saransh": {
        "status": "PASS",
        "alive_at_12s": true,
        "has_bad": false,
        "log": "/home/ubuntu/Trading_Runtime_Rahul/Logs/uat/smoke_start_saransh.log",
        "tail": "hon3.14/logging/__init__.py\", line 1555, in exception\n    self.error(msg, *args, exc_info=exc_info, **kwargs)\n  File \"/usr/lib/python3.14/logging/__init__.py\", line 1549, in error\n    self._log(ERROR, msg, args, **kwargs)\n  File \"/usr/lib/python3.14/logging/__init__.py\", line 1665, in _log\n    self.handle(record)\n  File \"/usr/lib/python3.14/logging/__init__.py\", line 1681, in handle\n    self.callHandlers(record)\n  File \"/usr/lib/python3.14/logging/__init__.py\", line 1737, in callHandlers\n    hdlr.handle(record)\n  File \"/usr/lib/python3.14/logging/__init__.py\", line 1027, in handle\n    self.emit(record)\n  File \"/home/ubuntu/rahul_Changes/core/incident_log_handler.py\", line 23, in emit\n    self.handleError(record)\nMessage: 'No error handlers are registered, logging exception.'\nArguments: ()\n"
      }
    }
  },
  "sizes": {
    "code_excl_venv_git": "21.8 MB",
    "venv": "173.6 MB",
    "runtime_desktop_total": "892.9 MB",
    "runtime_Credentials": "0.0 MB",
    "runtime_MarketData": "473.4 MB",
    "runtime_Cache": "404.0 MB",
    "runtime_Logs": "0.1 MB",
    "runtime_Data": "1.1 MB",
    "code_bytes": 22847038,
    "runtime_bytes": 936262399
  }
}
```
