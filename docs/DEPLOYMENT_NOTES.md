# Deployment Notes

## Arc Testnet

- Contract: `SourceBountyEscrow`
- Address: `0x4a38251e67229438235B0999cEb086Cb2987b55C`
- RPC: `https://rpc.testnet.arc.network`
- Chain ID: `5042002`
- Owner: `0xEd9EDd8586b20524CafA4F568413C504C9B03172`
- Relay signer: `0xEd9EDd8586b20524CafA4F568413C504C9B03172`
- Deployment command used: Foundry `forge script script/Deploy.s.sol:Deploy --broadcast`

## GenLayer Studionet

- Contract: `SourceBountyJudge`
- Address: `0xD98cCe08987CDb6Ca6A217FA1BD767c2EF5436aa`
- Transaction hash: `0x1b093130da8bf6acb55112fdc51b9f966302bad383dfcced494d3171cd0f71b2`
- Rubric version: `v1`
- Verification: `genlayer call 0xD98cCe08987CDb6Ca6A217FA1BD767c2EF5436aa get_rubric_version` returned `v1`
