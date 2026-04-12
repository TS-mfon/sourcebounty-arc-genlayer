# SourceBounty

SourceBounty is a scratch Arc + GenLayer dapp for paying people for cited, useful answers.

A creator posts a funded research bounty on Arc Testnet. A responder submits an answer and source URLs. A GenLayer Studionet intelligent contract checks whether the answer is relevant to the question and supported by citations. If accepted, the Arc contract can release the reward to the responder. If rejected or expired, the creator can refund.

## Deployed Network Details

| Layer | Network | Address |
| --- | --- | --- |
| Arc bounty escrow | Arc Testnet, chain `5042002` | `0x4a38251e67229438235B0999cEb086Cb2987b55C` |
| GenLayer judge | Studionet, chain `61999` | `0xD98cCe08987CDb6Ca6A217FA1BD767c2EF5436aa` |
| Owner / relay signer | Arc + GenLayer | `0xEd9EDd8586b20524CafA4F568413C504C9B03172` |

Arc RPC: `https://rpc.testnet.arc.network`

GenLayer RPC: `https://studio.genlayer.com/api`

## How It Works

1. Creator enters a research question, reward amount, and deadline.
2. Frontend sends bounty metadata to the relay API and can use the returned hash for on-chain bounty creation.
3. Responder submits answer text, an optional answer URL, and citation URLs.
4. GenLayer `SourceBountyJudge` evaluates the answer and stores a verdict.
5. The Arc escrow accepts the relay signer verdict digest and releases or refunds native Arc USDC.

## Local Development

Run the relay:

```bash
cd relay
python3 sourcebounty_service.py
```

Run the frontend:

```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8896 npm run dev
```

Run contract checks:

```bash
cd arc
forge test
genvm-lint check ../genlayer/contracts/sourcebounty_judge.py
```

## Vercel

Deploy from `frontend/` and set:

```bash
VITE_API_URL=<your-render-sourcebounty-relay-url>
```
