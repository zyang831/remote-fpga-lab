# D9 station cost (2026-10-15; D9-cost.csv). Purchasing cost only; commissioning time dropped by the user (ecommerce purchases, delivery time not counted).
Paid prices reported by the user (no receipts attached; "$" taken as USD):

| item | paid | note |
|---|---|---|
| Terasic DE25-Nano kit (incl. microSD and power supply) | USD 207 | terasic.com academic price; DigiKey US list USD 253.20 (0 in stock, 35-week lead time, 2026-10-15) |
| IMX519 16MP MIPI camera | USD 39 | list reference: about GBP 24 at The Pi Hut |
| UGREEN 1080P USB webcam (15728) | MYR 99.80 | Lazada/Shopee |
| UGREEN Cat6 patch cable | MYR 6.40 | Lazada/Shopee |
| microSD card, power supply, camera adapter | 0 | included in kit / not needed |

Total of one station: USD 246 + MYR 106.20. In one currency: about USD 272 at MYR 4.0855 per USD (Pluang, 22 Jul 2026, the most recent dated rate found; the rate in October 2026 was not confirmed, and 4.4 would give USD 270). Say "about USD 270".
Host: the existing lab PC (any machine, preferably Linux, runs the backend and Mender server) adds 0 for the lab; one lab PC serves many stations (see D12 for the load). Alternative of a Raspberry Pi 5 4GB per station as host: +USD 110 list (secondary sources, unverified; excludes its power supply, card and case) giving about USD 380 per station.
Caveats: the academic price may not be available to every reader (list USD 253.20, so about USD 318 per station at list); no receipts in the repository; one purchase per item.
Feeds: IV-A and VII-B ("what OTA removes": no host per station).
