# ClassFlow — Cashfree sandbox test build

## What this build does
1. Visitor opens the public ClassFlow website.
2. Visitor creates an account OR signs in.
3. Visitor selects Basic or Pro.
4. Website calls the backend.
5. Backend creates a Cashfree SANDBOX order using secret keys.
6. Website opens Cashfree hosted checkout.
7. Cashfree returns to the website.
8. Webhook endpoint is prepared for server-side payment verification.

## Important
GitHub Pages is only the frontend. The Cashfree secret key MUST stay on the backend.
Do not put `.env` or real Cashfree secrets in GitHub.

## Deploy
- Put `backend.py`, `requirements.txt` and environment variables on a public HTTPS Python host.
- Set `PUBLIC_SITE_URL` to the GitHub Pages URL.
- Set `WEBHOOK_URL` to `https://YOUR-BACKEND-DOMAIN/api/cashfree/webhook`.
- In `index.html`, replace `https://YOUR-BACKEND-DOMAIN` in `API_BASE` with your backend URL.
- Upload the four HTML files to the GitHub CLASSFLOW repository root.

## Sandbox
Use Cashfree sandbox App ID and Secret Key only. Test orders are not real production charges.

## Production hardening still required
- Restrict CORS to the ClassFlow domain.
- Verify Cashfree webhook signatures using the current Cashfree specification.
- Make webhook/order updates idempotent.
- Move auth/order storage to the production ClassFlow database.
- Connect successful payment to the real subscription/billing ledger.
- Add proper password reset, session expiry/revocation, rate limiting and HTTPS.
