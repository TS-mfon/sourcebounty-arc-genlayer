import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { createPublicClient, createWalletClient, custom, http, isAddress, keccak256, parseEther, toHex } from "viem";
import "./styles.css";

declare global {
  interface Window {
    ethereum?: {
      request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
    };
  }
}

const API_URL = import.meta.env.VITE_API_URL || "https://sourcebounty-relay.onrender.com";
const ARC_CHAIN_ID = 5042002;
const ARC_RPC_URL = "https://rpc.testnet.arc.network";
const ARC_ESCROW_CONTRACT = "0x4a38251e67229438235B0999cEb086Cb2987b55C";
const GENLAYER_JUDGE_CONTRACT = "0xD98cCe08987CDb6Ca6A217FA1BD767c2EF5436aa";
const GENLAYER_NETWORK = "studionet";

const arcTestnet = {
  id: ARC_CHAIN_ID,
  name: "Arc Testnet",
  nativeCurrency: { name: "Arc Testnet Token", symbol: "ARC", decimals: 18 },
  rpcUrls: { default: { http: [ARC_RPC_URL] } },
} as const;

const bountyAbi = [
  { name: "nextBountyId", type: "function", stateMutability: "view", inputs: [], outputs: [{ type: "uint256" }] },
  {
    name: "createBounty",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "questionHash", type: "bytes32" },
      { name: "reward", type: "uint256" },
      { name: "deadline", type: "uint64" },
    ],
    outputs: [{ type: "uint256" }],
  },
  { name: "fundBounty", type: "function", stateMutability: "payable", inputs: [{ name: "bountyId", type: "uint256" }], outputs: [] },
  {
    name: "submitAnswer",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "bountyId", type: "uint256" },
      { name: "answerHash", type: "bytes32" },
    ],
    outputs: [],
  },
] as const;

type Role = "provider" | "hunter";
type Page = "home" | "provider" | "hunter" | "bounties" | "tutorial" | "status";
type Health = { arcEscrowContract: string; genlayerJudgeContract: string; genlayerNetwork: string; arcChainId?: number };
type Bounty = { id: string; creator: string; question: string; reward: string; deadline: number; status: string; onchainBountyId?: string; fundingTxHash?: string };
type Verdict = { accepted: boolean | null; summary?: string; reasonCodes?: string[]; verdictDigest?: string; genlayerTxHash?: string; recordTxHash?: string; rewardTxHash?: string; settlementStatus?: string };
type Answer = { id: string; bountyId: string; responder: string; answer: string; answerUrl: string; citationUrls: string[]; accepted: number | null; verdict: Verdict | null; createdAt: number; answerTxHash?: string };

const initialBountyForm = { question: "", reward: "", deadline: "" };
const initialAnswerForm = { bountyId: "", onchainBountyId: "", responder: "", answer: "", answerUrl: "", citationUrls: "" };
const nowPlusDay = () => new Date(Date.now() + 86400 * 1000).toISOString().slice(0, 16);
const hash32 = (value: string) => keccak256(toHex(value));
const short = (value: string) => (value ? `${value.slice(0, 6)}...${value.slice(-4)}` : "");
const splitUrls = (value: string) => value.split(",").map((url) => url.trim()).filter(Boolean);
const toTimestamp = (value: string) => Math.floor(new Date(value).getTime() / 1000);

function App() {
  const [page, setPage] = useState<Page>("home");
  const [wallets, setWallets] = useState<Record<Role, string>>({ provider: "", hunter: "" });
  const [health, setHealth] = useState<Health | null>(null);
  const [bounties, setBounties] = useState<Bounty[]>([]);
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [message, setMessage] = useState("Connect a role wallet to start.");
  const [busy, setBusy] = useState(false);
  const [bountyForm, setBountyForm] = useState({ question: "Find public evidence that Arc settlement can support low-latency stablecoin payments.", reward: "0.001", deadline: nowPlusDay() });
  const [answerForm, setAnswerForm] = useState({ ...initialAnswerForm, answer: "I found the relevant public references and summarized the settlement implications." });
  const selectedBounty = useMemo(() => bounties.find((bounty) => bounty.id === answerForm.bountyId), [bounties, answerForm.bountyId]);

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    try {
      const [healthRes, bountiesRes, answersRes] = await Promise.all([fetch(`${API_URL}/health`), fetch(`${API_URL}/bounties`), fetch(`${API_URL}/answers`)]);
      if (!healthRes.ok || !bountiesRes.ok || !answersRes.ok) throw new Error("Relay returned an unavailable response.");
      setHealth(await healthRes.json());
      setBounties((await bountiesRes.json()).bounties || []);
      setAnswers((await answersRes.json()).answers || []);
      setMessage("Relay online. Arc bounty contract and GenLayer judge are configured.");
    } catch (error) {
      setHealth({ arcEscrowContract: ARC_ESCROW_CONTRACT, genlayerJudgeContract: GENLAYER_JUDGE_CONTRACT, genlayerNetwork: GENLAYER_NETWORK, arcChainId: ARC_CHAIN_ID });
      setMessage(`Relay is starting or temporarily unavailable: ${error instanceof Error ? error.message : "unknown error"}`);
    }
  }

  async function connectWallet(role: Role) {
    if (!window.ethereum) return setMessage("Install a browser wallet that supports Arc Testnet.");
    try {
      await ensureArcNetwork();
      const accounts = (await window.ethereum.request({ method: "eth_requestAccounts" })) as string[];
      setWallets((current) => ({ ...current, [role]: accounts[0] || "" }));
      setAnswerForm((form) => role === "hunter" ? { ...form, responder: accounts[0] || "" } : form);
      setMessage(`${role === "provider" ? "Bounty provider" : "Bounty hunter"} wallet connected: ${short(accounts[0] || "")}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Wallet connection failed.");
    }
  }

  async function ensureArcNetwork() {
    if (!window.ethereum) throw new Error("No wallet provider found.");
    const chainId = `0x${ARC_CHAIN_ID.toString(16)}`;
    try {
      await window.ethereum.request({ method: "wallet_switchEthereumChain", params: [{ chainId }] });
    } catch {
      await window.ethereum.request({
        method: "wallet_addEthereumChain",
        params: [{ chainId, chainName: "Arc Testnet", nativeCurrency: arcTestnet.nativeCurrency, rpcUrls: [ARC_RPC_URL] }],
      });
    }
  }

  async function createAndFundBounty() {
    if (!wallets.provider || !isAddress(wallets.provider)) return setMessage("Connect the bounty provider wallet first.");
    if (!bountyForm.question.trim()) return setMessage("Add a bounty question.");
    const deadline = toTimestamp(bountyForm.deadline);
    if (!deadline || deadline <= Math.floor(Date.now() / 1000)) return setMessage("Deadline must be in the future.");
    setBusy(true);
    try {
      await ensureArcNetwork();
      const publicClient = createPublicClient({ chain: arcTestnet, transport: http(ARC_RPC_URL) });
      const walletClient = createWalletClient({ chain: arcTestnet, transport: custom(window.ethereum!) });
      const onchainBountyId = (await publicClient.readContract({ address: ARC_ESCROW_CONTRACT, abi: bountyAbi, functionName: "nextBountyId" })) as bigint;
      const value = parseEther(bountyForm.reward);
      setMessage("Creating the Arc bounty...");
      const createHash = await walletClient.writeContract({
        account: wallets.provider as `0x${string}`,
        address: ARC_ESCROW_CONTRACT,
        abi: bountyAbi,
        functionName: "createBounty",
        args: [hash32(bountyForm.question), value, BigInt(deadline)],
      });
      await publicClient.waitForTransactionReceipt({ hash: createHash });
      setMessage("Funding the bounty treasury from the provider wallet...");
      const fundingTxHash = await walletClient.writeContract({
        account: wallets.provider as `0x${string}`,
        address: ARC_ESCROW_CONTRACT,
        abi: bountyAbi,
        functionName: "fundBounty",
        args: [onchainBountyId],
        value,
      });
      await publicClient.waitForTransactionReceipt({ hash: fundingTxHash });

      const res = await fetch(`${API_URL}/bounties`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ creator: wallets.provider, ...bountyForm, deadline, onchainBountyId: onchainBountyId.toString(), fundingTxHash }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not save the funded bounty.");
      setAnswerForm((form) => ({ ...form, bountyId: data.bountyId, onchainBountyId: onchainBountyId.toString() }));
      setMessage(`Bounty funded and listed: ${data.bountyId}. Treasury tx: ${short(fundingTxHash)}`);
      setPage("bounties");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Create and fund flow failed.");
    } finally {
      setBusy(false);
    }
  }

  async function submitAnswer() {
    const onchainBountyId = answerForm.onchainBountyId || selectedBounty?.onchainBountyId || "";
    if (!wallets.hunter || !isAddress(wallets.hunter)) return setMessage("Connect the bounty hunter wallet first.");
    if (!answerForm.bountyId || !answerForm.answer.trim()) return setMessage("Choose a bounty and add an answer.");
    if (!isAddress(answerForm.responder)) return setMessage("Responder wallet must be a valid EVM address.");
    setBusy(true);
    try {
      await ensureArcNetwork();
      let answerTxHash = "";
      if (onchainBountyId) {
        const publicClient = createPublicClient({ chain: arcTestnet, transport: http(ARC_RPC_URL) });
        const walletClient = createWalletClient({ chain: arcTestnet, transport: custom(window.ethereum!) });
        setMessage("Submitting the answer hash to the Arc bounty contract...");
        answerTxHash = await walletClient.writeContract({
          account: wallets.hunter as `0x${string}`,
          address: ARC_ESCROW_CONTRACT,
          abi: bountyAbi,
          functionName: "submitAnswer",
          args: [BigInt(onchainBountyId), hash32(JSON.stringify(answerForm))],
        });
        await publicClient.waitForTransactionReceipt({ hash: answerTxHash as `0x${string}` });
      }
      const res = await fetch(`${API_URL}/answers`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...answerForm, onchainBountyId, answerTxHash, citationUrls: splitUrls(answerForm.citationUrls) }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.urlProblems?.map((item: { url: string; reason: string }) => `${item.url}: ${item.reason}`).join(" | ") || data.error || "Could not submit answer.");
      setMessage(`Answer ${data.answerId}: ${data.verdict.summary}`);
      setPage("status");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Submit answer failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <header className="topbar">
        <button className="brand" onClick={() => setPage("home")}><span className="logo">◎</span> SourceBounty</button>
        <nav>{(["bounties", "provider", "hunter", "tutorial", "status"] as Page[]).map((item) => <button className={page === item ? "active" : ""} onClick={() => setPage(item)} key={item}>{item}</button>)}</nav>
      </header>
      {page === "home" && <Landing setPage={setPage} connectWallet={connectWallet} wallets={wallets} />}
      {page === "provider" && <ProviderPortal form={bountyForm} setForm={setBountyForm} wallet={wallets.provider} connect={() => connectWallet("provider")} submit={createAndFundBounty} busy={busy} />}
      {page === "hunter" && <HunterPortal bounties={bounties} form={answerForm} setForm={setAnswerForm} wallet={wallets.hunter} connect={() => connectWallet("hunter")} submit={submitAnswer} busy={busy} />}
      {page === "bounties" && <FindBounties bounties={bounties} answers={answers} setPage={setPage} setAnswerForm={setAnswerForm} />}
      {page === "tutorial" && <Tutorial />}
      {page === "status" && <Status health={health} message={message} refresh={refresh} bounties={bounties} answers={answers} />}
      <aside className="toast">{message}</aside>
    </main>
  );
}

function Landing({ setPage }: { setPage: (page: Page) => void; connectWallet: (role: Role) => void; wallets: Record<Role, string> }) {
  return <section className="hero page-rise"><div className="hero-copy"><p className="eyebrow">Research bounties with escrow discipline</p><h1>Fund questions. Reward useful answers.</h1><p>SourceBounty lets a bounty provider lock an Arc reward for a research question and lets bounty hunters submit answers for GenLayer-assisted review. Public citations are checked before they enter the verdict flow.</p><div className="actions"><button className="primary" onClick={() => setPage("provider")}>Create a funded bounty</button><button className="secondary" onClick={() => setPage("bounties")}>Find bounties</button></div></div><div className="hero-panel"><span>Ask a precise question</span><span>Lock the reward</span><span>Submit cited answers</span><span>Review, release, or refund</span></div></section>;
}

function ProviderPortal({ form, setForm, wallet, connect, submit, busy }: { form: typeof initialBountyForm; setForm: (form: typeof initialBountyForm) => void; wallet: string; connect: () => void; submit: () => void; busy: boolean }) {
  return <section className="panel page-rise"><div className="section-head"><p className="eyebrow">Bounty provider portal</p><h2>Create and fund a bounty</h2><p>The reward is deducted from the connected provider wallet and locked in the deployed Arc bounty contract.</p></div><div className="form-grid"><label className="wide">Question<span>Write a specific question with clear acceptance standards.</span><textarea value={form.question} onChange={(e) => setForm({ ...form, question: e.target.value })} /></label><label>Reward amount<span>Amount sent to the escrow contract. The current deployed contract accepts Arc native testnet value.</span><input value={form.reward} onChange={(e) => setForm({ ...form, reward: e.target.value })} /></label><label>Deadline<span>Used for refund timing if no answer is accepted.</span><input type="datetime-local" value={form.deadline} onChange={(e) => setForm({ ...form, deadline: e.target.value })} /></label></div><div className="actions"><button className="secondary" onClick={connect}>{wallet ? `Provider ${short(wallet)}` : "Connect provider wallet"}</button><button className="primary" disabled={busy} onClick={submit}>{busy ? "Processing..." : "Create, fund, and list bounty"}</button></div></section>;
}

function HunterPortal({ bounties, form, setForm, wallet, connect, submit, busy }: { bounties: Bounty[]; form: typeof initialAnswerForm; setForm: (form: typeof initialAnswerForm) => void; wallet: string; connect: () => void; submit: () => void; busy: boolean }) {
  return <section className="panel page-rise"><div className="section-head"><p className="eyebrow">Bounty hunter portal</p><h2>Submit a cited answer</h2><p>Citation links are optional. If you add them, they must be public; gated X, Instagram, and similar links will be rejected with a clear message.</p></div><div className="form-grid"><label>Bounty ID<span>Select a relay bounty or paste the bounty ID.</span><select value={form.bountyId} onChange={(e) => { const bounty = bounties.find((item) => item.id === e.target.value); setForm({ ...form, bountyId: e.target.value, onchainBountyId: bounty?.onchainBountyId || "" }); }}><option value="">Choose a bounty</option>{bounties.map((bounty) => <option key={bounty.id} value={bounty.id}>{bounty.question.slice(0, 72)} - {bounty.id}</option>)}</select></label><label>On-chain bounty ID<span>Auto-filled for funded bounties; required for Arc contract submission.</span><input value={form.onchainBountyId} onChange={(e) => setForm({ ...form, onchainBountyId: e.target.value })} /></label><label>Responder wallet<span>The address that should receive reward after acceptance.</span><input value={form.responder} onChange={(e) => setForm({ ...form, responder: e.target.value })} placeholder="0x..." /></label><label>Answer URL<span>Optional public link to a longer answer.</span><input value={form.answerUrl} onChange={(e) => setForm({ ...form, answerUrl: e.target.value })} placeholder="https://..." /></label><label className="wide">Answer<span>Write the researched answer and reasoning.</span><textarea value={form.answer} onChange={(e) => setForm({ ...form, answer: e.target.value })} /></label><label className="wide">Citation URLs<span>Optional comma-separated public links. Avoid gated social URLs.</span><input value={form.citationUrls} onChange={(e) => setForm({ ...form, citationUrls: e.target.value })} placeholder="https://example.com/source" /></label></div><div className="actions"><button className="secondary" onClick={connect}>{wallet ? `Hunter ${short(wallet)}` : "Connect hunter wallet"}</button><button className="primary" disabled={busy} onClick={submit}>{busy ? "Submitting..." : "Submit answer"}</button></div></section>;
}

function FindBounties({ bounties, answers, setPage, setAnswerForm }: { bounties: Bounty[]; answers: Answer[]; setPage: (page: Page) => void; setAnswerForm: React.Dispatch<React.SetStateAction<typeof initialAnswerForm>> }) {
  return <section className="panel page-rise"><div className="section-head"><p className="eyebrow">Bounty board</p><h2>Find open bounties</h2><p>Browse research tasks created through the relay and backed by Arc escrow funding transactions.</p></div><div className="cards">{bounties.length === 0 ? <p className="empty">No bounties listed yet.</p> : bounties.map((bounty) => { const bountyAnswers = answers.filter((answer) => answer.bountyId === bounty.id); const latest = bountyAnswers[0]; return <article className="job-card" key={bounty.id}><div><span className="pill">{bounty.status}</span><span className="pill">On-chain #{bounty.onchainBountyId || "pending"}</span><span className="pill">{bountyAnswers.length} answer{bountyAnswers.length === 1 ? "" : "s"}</span></div><h3>{bounty.question}</h3><dl><div><dt>Reward</dt><dd>{bounty.reward}</dd></div><div><dt>Provider</dt><dd>{short(bounty.creator)}</dd></div><div><dt>Funding tx</dt><dd>{hashLink(bounty.fundingTxHash)}</dd></div><div><dt>Latest verdict</dt><dd>{latest?.verdict ? verdictLabel(latest.verdict) : "No answer yet"}</dd></div></dl><button className="primary" onClick={() => { setAnswerForm((form) => ({ ...form, bountyId: bounty.id, onchainBountyId: bounty.onchainBountyId || "" })); setPage("hunter"); }}>Submit answer</button></article>; })}</div></section>;
}

function Tutorial() {
  return <section className="panel tutorial page-rise"><p className="eyebrow">Tutorial</p><h2>How SourceBounty works</h2><ol><li>Provider connects a provider wallet and writes the research question, reward, and deadline.</li><li>The app creates the Arc bounty and funds it from the provider wallet in two wallet transactions.</li><li>Hunter connects a separate wallet, picks a bounty, and submits an answer hash to Arc plus answer details to the relay.</li><li>Optional citation links are checked before submission. If GenLayer cannot access a link, the relay tells the user before review.</li><li>The relay calls the GenLayer judge, records the verdict on Arc, and releases the reward automatically when the answer is accepted.</li></ol></section>;
}

function Status({ health, message, refresh, bounties, answers }: { health: Health | null; message: string; refresh: () => void; bounties: Bounty[]; answers: Answer[] }) {
  return <section className="panel status page-rise"><p className="eyebrow">Network status</p><h2>Live configuration</h2><p>Arc bounty contract: <code>{health?.arcEscrowContract || ARC_ESCROW_CONTRACT}</code></p><p>GenLayer judge: <code>{health?.genlayerJudgeContract || GENLAYER_JUDGE_CONTRACT}</code></p><p>Network: <code>{health?.genlayerNetwork || GENLAYER_NETWORK}</code></p><p>Relay API: <code>{API_URL}</code></p><p>{message}</p><button className="secondary" onClick={refresh}>Refresh status</button><div className="activity"><h3>Answer process</h3>{answers.length === 0 ? <p className="empty">No answers submitted yet.</p> : answers.map((answer) => <ProcessCard key={answer.id} answer={answer} bounty={bounties.find((bounty) => bounty.id === answer.bountyId)} />)}</div></section>;
}

function ProcessCard({ answer, bounty }: { answer: Answer; bounty?: Bounty }) {
  const verdict = answer.verdict;
  return <article className="process-card"><div><span className="pill">{verdictLabel(verdict)}</span><span className="pill">{answer.id}</span></div><h3>{bounty?.question || answer.bountyId}</h3><p>{answer.answer}</p><dl><div><dt>Responder</dt><dd>{short(answer.responder)}</dd></div><div><dt>On-chain bounty</dt><dd>#{bounty?.onchainBountyId || "unknown"}</dd></div><div><dt>Funding tx</dt><dd>{hashLink(bounty?.fundingTxHash)}</dd></div><div><dt>Answer tx</dt><dd>{hashLink(answer.answerTxHash)}</dd></div><div><dt>GenLayer tx</dt><dd>{hashLink(verdict?.genlayerTxHash)}</dd></div><div><dt>Record verdict tx</dt><dd>{hashLink(verdict?.recordTxHash)}</dd></div><div><dt>Reward tx</dt><dd>{hashLink(verdict?.rewardTxHash)}</dd></div><div><dt>Digest</dt><dd>{short(verdict?.verdictDigest || "")}</dd></div></dl><p>{verdict?.summary || "Waiting for relay update."}</p>{verdict?.reasonCodes?.length ? <p className="reasons">{verdict.reasonCodes.join(", ")}</p> : null}</article>;
}

function verdictLabel(verdict?: Verdict | null) {
  if (!verdict) return "not submitted";
  if (verdict.accepted === null) return "evaluating";
  if (verdict.reasonCodes?.includes("SETTLEMENT_FAILED")) return "settlement failed";
  return verdict.accepted ? "accepted" : "rejected";
}

function hashLink(value?: string) {
  if (!value) return "pending";
  const href = `https://explorer.testnet.arc.network/tx/${value}`;
  return <a href={href} target="_blank" rel="noreferrer">{short(value)}</a>;
}

createRoot(document.getElementById("root")!).render(<App />);
