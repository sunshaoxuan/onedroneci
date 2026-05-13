# Reference Materials

This directory keeps sanitized build/deployment references collected from older
or external OHR environments. They are not the active build definitions.

| File | Purpose |
|------|---------|
| `ohr-back-drone-reference.yml` | Sanitized `.drone.yml` reference from a previous standalone OHR backend Drone setup. Useful for comparing runner type, host volumes, trigger shape, and package/startup steps. |

Sensitive runtime values from the source environment were intentionally removed.
Do not add passwords, tokens, private URLs with embedded credentials, or concrete
production parameter values to this directory.
