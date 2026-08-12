# Wire repair approval Action App

Standalone UiPath Coded Action App for the WIRE-8841 human decision. The
`action-schema.json` contract carries exactly the seven C1 escalation fields:
payment, proposal, gate, reason, evidence, cutoff time, and permitted actions.
The proposal is an `inOut` so an authorized reviewer can edit the value without
changing the policy-evaluated field. Approve, Edit, Reject, and Escalate are the
only outcomes.

This app uses only `@uipath/coded-action-app`. It does not use platform SDK
services, does not require an OAuth configuration to build, and contains no
tenant binding or credentials. Deployment and the Flow `appSystemName` binding
remain intentionally pending until the nominated staging tenant is available.

```powershell
npm install --registry https://registry.npmjs.org
npm run build
```
