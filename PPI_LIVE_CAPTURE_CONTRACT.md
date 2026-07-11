# PPI Live Capture Contract

PPI live capture observes `WPSFD4`, `WPUFD4`, `WPSFD49116`, and
`WPUFD49116` only during the first 24 hours after a registered PPI release.
It requires the exact reference period and all four metrics. The stored
`as_released.json` is immutable and records `live_release_capture`,
`as_released_capture`, and `not_as_released: false`. After the window expires,
use historical backfill instead; a current API snapshot must not be labelled as
an as-released capture.
