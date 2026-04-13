import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { isAddress } from "viem";
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
const ARC_ESCROW_CONTRACT = "0x4a38251e67229438235B0999cEb086Cb2987b55C";
const GENLAYER_JUDGE_CONTRACT = "0xD98cCe08987CDb6Ca6A217FA1BD767c2EF5436aa";
const GENLAYER_NETWORK = "studionet";

type Health = { arcEscrowContract: string; genlayerJudgeContract: string; genlayerNetwork: string };
type Bounty = { id: string; creator: string; question: string; reward: string; deadline: number; status: string };

function App() {
  const [wallet, setWallet] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [bounties, setBounties] = useState<Bounty[]>([]);
  const [message, setMessage] = useState("");
  const [bountyForm, setBountyForm] = useState({
    question: "What are the best public sources proving Arc stablecoin finality and settlement behavior?",
    reward: "1",
    deadline: String(Math.floor(Date.now() / 1000) + 86400),
  });
  const [answerForm, setAnswerForm] = useState({
    bountyId: "",
    responder: "",
    answer: "Answer with cited docs and a short risk summary.",
    answerUrl: "",
    citationUrls: "https://example.com",
  });

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    try {
      const [healthRes, bountiesRes] = await Promise.all([fetch(`${API_URL}/health`), fetch(`${API_URL}/bounties`)]);
      if (!healthRes.ok || !bountiesRes.ok) {
        throw new Error("Backend returned an unavailable response.");
      }
      setHealth(await healthRes.json());
      const data = await bountiesRes.json();
      setBounties(data.bounties || []);
      setMessage("Backend connected. Network configuration loaded.");
    } catch (error) {
      setHealth({
        arcEscrowContract: ARC_ESCROW_CONTRACT,
        genlayerJudgeContract: GENLAYER_JUDGE_CONTRACT,
        genlayerNetwork: GENLAYER_NETWORK,
      });
      setMessage(`Backend is starting or temporarily unavailable: ${error instanceof Error ? error.message : "unknown error"}`);
    }
  }

  async function connectWallet() {
    if (!window.ethereum) {
      setMessage("Install a wallet that supports Arc Testnet.");
      return;
    }
    const accounts = (await window.ethereum.request({ method: "eth_requestAccounts" })) as string[];
    setWallet(accounts[0] || "");
    await window.ethereum.request({ method: "wallet_switchEthereumChain", params: [{ chainId: `0x${ARC_CHAIN_ID.toString(16)}` }] });
  }

  async function createBounty() {
    if (!wallet || !isAddress(wallet)) {
      setMessage("Connect a valid creator wallet before creating a bounty.");
      return;
    }
    const res = await fetch(`${API_URL}/bounties`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ creator: wallet, ...bountyForm }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMessage(data.error || "Could not create bounty.");
      return;
    }
    setMessage(`Bounty created: ${data.bountyId}`);
    setAnswerForm((form) => ({ ...form, bountyId: data.bountyId }));
    await refresh();
  }

  async function submitAnswer() {
    if (!answerForm.bountyId || !answerForm.answer) {
      setMessage("Choose a bounty ID and add answer text before submitting.");
      return;
    }
    if (!isAddress(answerForm.responder)) {
      setMessage("Responder wallet must be a valid EVM address.");
      return;
    }
    const citationUrls = answerForm.citationUrls.split(",").map((url) => url.trim()).filter(Boolean);
    const res = await fetch(`${API_URL}/answers`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...answerForm, citationUrls }),
    });
    const data = await res.json();
    if (!res.ok) {
      setMessage(data.error || "Could not submit answer.");
      return;
    }
    setMessage(`Answer ${data.answerId}: ${data.verdict.summary}`);
  }

  return (
    <main>
      <section className="hero">
        <div className="icon-row"><span className="icon">SB</span><span className="icon">ARC</span><span className="icon">GL</span></div>
        <p className="eyebrow">Arc + GenLayer</p>
        <h1>SourceBounty</h1>
        <p>Post funded research questions on Arc and use GenLayer Studionet to check whether answers are cited and relevant before reward release.</p>
        <button onClick={connectWallet}>{wallet ? `${wallet.slice(0, 6)}...${wallet.slice(-4)}` : "Connect Wallet"}</button>
      </section>

      <section className="grid">
        <div className="card">
          <h2><span className="mini-icon">01</span>Create Bounty</h2>
          <label>Question<span>The research question you want solved with cited sources.</span><textarea value={bountyForm.question} onChange={(e) => setBountyForm({ ...bountyForm, question: e.target.value })} /></label>
          <label>Reward<span>Native Arc Testnet USDC amount locked for the accepted answer.</span><input value={bountyForm.reward} onChange={(e) => setBountyForm({ ...bountyForm, reward: e.target.value })} /></label>
          <label>Deadline<span>Unix timestamp after which creator refund becomes available.</span><input value={bountyForm.deadline} onChange={(e) => setBountyForm({ ...bountyForm, deadline: e.target.value })} /></label>
          <button onClick={createBounty}>Create Bounty</button>
        </div>

        <div className="card">
          <h2><span className="mini-icon">02</span>Submit Answer</h2>
          <label>Bounty ID<span>Use the ID returned after bounty creation.</span><input value={answerForm.bountyId} onChange={(e) => setAnswerForm({ ...answerForm, bountyId: e.target.value })} /></label>
          <label>Responder Wallet<span>The address that should receive the reward if accepted.</span><input value={answerForm.responder} onChange={(e) => setAnswerForm({ ...answerForm, responder: e.target.value })} /></label>
          <label>Answer<span>The researched answer GenLayer should evaluate.</span><textarea value={answerForm.answer} onChange={(e) => setAnswerForm({ ...answerForm, answer: e.target.value })} /></label>
          <label>Answer URL<span>Optional link to a longer answer.</span><input value={answerForm.answerUrl} onChange={(e) => setAnswerForm({ ...answerForm, answerUrl: e.target.value })} /></label>
          <label>Citation URLs<span>Comma-separated source URLs that support the answer.</span><input value={answerForm.citationUrls} onChange={(e) => setAnswerForm({ ...answerForm, citationUrls: e.target.value })} /></label>
          <button onClick={submitAnswer}>Generate Verdict Preview</button>
        </div>
      </section>

      <section className="card">
        <h2><span className="mini-icon">03</span>Network</h2>
        <p>Arc bounty contract: {health?.arcEscrowContract || ARC_ESCROW_CONTRACT}</p>
        <p>GenLayer judge: {health?.genlayerJudgeContract || GENLAYER_JUDGE_CONTRACT} on {health?.genlayerNetwork || GENLAYER_NETWORK}</p>
        <p>Relay API: {API_URL}</p>
        <p>{message}</p>
      </section>

      <section className="card">
        <h2><span className="mini-icon">04</span>Bounties</h2>
        {bounties.length === 0 ? <p>No bounties created yet.</p> : bounties.map((bounty) => <p key={bounty.id}>{bounty.id} - {bounty.question} - {bounty.status} - {bounty.reward} Arc USDC</p>)}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
