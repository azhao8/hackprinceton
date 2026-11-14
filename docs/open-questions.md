# Open questions

Everything not yet decided, with a recommendation. When one is settled, add a file to `decisions/` and remove it here.

## Product

| # | Question | Recommendation |
| --- | --- | --- |
| P-1 | Which use case? | Pick around Sat noon. Without a gripper, the strongest fits are fetch-and-carry with a tray, find-my-things, the robot pet and telepresence (see `04-product.md`) |
| P-2 | Which main track and special tracks? | Pick around Sat noon. Leading idea: Healthcare as the main track; Best Hardware, Best Physical AI and Amazon Practical AI as extras (see `05-event.md`) |

## Technical

| # | Question | Recommendation |
| --- | --- | --- |
| T-4 | How the phone's camera reaches the server (was B4 and T-4) | Go straight to the phone page over HTTPS: agents make the certificate or tunnel cheap, and it keeps the face on screen. Vision develops on a desk camera behind a frame-source interface meanwhile, so this can be settled later |
