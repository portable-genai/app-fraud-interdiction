"use client";

import { useEffect, useState } from "react";

// Every request goes to THIS origin. The browser never learns the service's address and never
// holds its credential; the route handler under /api/agent forwards, having discarded whatever
// identity the client tried to assert.
const API = "/api/agent";

// Mirrors the service's seeded local personas. The picker is a DEV convenience: the server
// validates the selection against its own list, so a hand-crafted value cannot invent a persona.
const PERSONAS = ["analyst", "approver", "auditor", "other-tenant"];

interface CardSummary {
  name?: string;
  description?: string;
  skills?: { id: string; name: string }[];
}

export default function Home() {
  const [persona, setPersona] = useState(PERSONAS[0]);
  const [eventId, setEventId] = useState("sg-block-demo");
  const [market, setMarket] = useState("SG");
  const [payerRef, setPayerRef] = useState("payer-coached");
  const [payeeRef, setPayeeRef] = useState("sg-mule-2d");
  const [amountMinor, setAmountMinor] = useState("600000");
  const [callRef, setCallRef] = useState("call-scam-sg");
  const [result, setResult] = useState("");
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [card, setCard] = useState<CardSummary | null>(null);

  // The service names itself, so this UI carries no hardcoded product name to go stale.
  useEffect(() => {
    let live = true;
    fetch(API + "/.well-known/agent-card.json", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => {
        if (live) setCard(body as CardSummary | null);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailed(false);
    try {
      const response = await fetch(API + "/v1/interdict", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Dev-Persona": persona },
        body: JSON.stringify({
          event_id: eventId,
          market,
          payer_ref: payerRef,
          payee_ref: payeeRef,
          amount_minor: Number(amountMinor),
          currency: "SGD",
          call_ref: callRef,
        }),
      });
      const body = await response.text();
      setFailed(!response.ok);
      setResult(body);
    } catch (error) {
      setFailed(true);
      setResult(String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>{card?.name ?? "Agent console"}</h1>
      <p className="sub">
        {card?.description ??
          "Score an in-flight payment. The allow / warn / hold / block verdict is deterministic, cited, and routed to a human reviewer on a hold or block."}
      </p>

      <form onSubmit={submit}>
        <fieldset>
          <legend>Who you are</legend>
          <label>
            Seeded dev persona (local profile only; the server resolves identity, not this field)
            <select value={persona} onChange={(event) => setPersona(event.target.value)}>
              {PERSONAS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </fieldset>

        <fieldset>
          <legend>The payment</legend>
          <label>
            Event id
            <input value={eventId} onChange={(event) => setEventId(event.target.value)} />
          </label>
          <label>
            Market
            <input value={market} onChange={(event) => setMarket(event.target.value)} />
          </label>
          <label>
            Payer reference
            <input value={payerRef} onChange={(event) => setPayerRef(event.target.value)} />
          </label>
          <label>
            Payee reference
            <input value={payeeRef} onChange={(event) => setPayeeRef(event.target.value)} />
          </label>
          <label>
            Amount (minor units)
            <input
              value={amountMinor}
              inputMode="numeric"
              onChange={(event) => setAmountMinor(event.target.value)}
            />
          </label>
          <label>
            Linked call reference (optional)
            <input value={callRef} onChange={(event) => setCallRef(event.target.value)} />
          </label>
          <button type="submit" disabled={busy}>
            {busy ? "Working" : "Assess this payment"}
          </button>
        </fieldset>
      </form>

      {result ? <pre className={failed ? "result error" : "result"}>{result}</pre> : null}

      <footer>
        Synthetic, obviously fictional data only. Identity is resolved server-side and the
        client-asserted actor is discarded; see ui/README.md for the embedding contract.
      </footer>
    </main>
  );
}
