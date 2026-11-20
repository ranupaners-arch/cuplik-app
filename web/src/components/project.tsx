"use client";
import { Button } from "@mantine/core";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, post, type Project, type Transcript } from "@/lib/api";
import { CreateForm } from "./create-form";

export function ProjectPage({ id }: { id: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState("");
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true, pending = false;
    const events = new EventSource(`/api/projects/${id}/events`);
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const value = await api<Project>(`/projects/${id}`);
        if (active) setProject(value);
        if (["done", "failed"].includes(value.transcript_status)) {
          events.close(); clearInterval(timer);
          if (value.transcript_status === "done") {
            const result = await api<Transcript>(`/projects/${id}/transcript`);
            if (active) setTranscript(result);
          }
        }
      } catch (e) { if (active) setError((e as Error).message); }
      finally { pending = false; }
    };
    const timer = setInterval(() => void load(), 4000);
    events.addEventListener("progress", () => void load());
    events.addEventListener("complete", () => { events.close(); void load(); });
    void load();
    return () => { active = false; events.close(); clearInterval(timer); };
  }, [id, revision]);
  if (error) return <p role="alert" className="error">{error}</p>;
  if (!project) return <p>Memuat proyek…</p>;
  return <><h1>{project.title}</h1><p>Sumber dan transkrip proyek ini dipakai kembali untuk setiap output.</p>
    <section aria-label="Progres sumber"><p>Ingest: {project.ingest_status} · Transkripsi: <strong data-testid="transcript-status">{project.transcript_status}</strong> · Tahap: {project.stage}</p><progress max={1} value={project.progress} aria-label="Kemajuan tahapan sumber" /><p role="status">{project.note}</p>{project.error && <p role="alert" className="error">{project.error}</p>}{project.transcript_status === "failed" && <Button type="submit" disabled={busy} onClick={async () => { setBusy(true); setError(""); try { await post(`/projects/${id}/retry`); setRevision(v => v+1); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>Coba ulang ingest/transkripsi</Button>}</section>
    {transcript && <section><h2>Transkrip sumber</h2><p>Bahasa: {transcript.language} · {transcript.sentences.length} kalimat · {transcript.words?.length ?? 0} kata bertimestamp.</p>{transcript.warnings?.map((warning, i) => <p key={i}>{warning}</p>)}<a href={`/api/projects/${id}/transcript`} target="_blank" rel="noreferrer">Buka transkrip JSON</a><details><summary>Lihat kalimat dan timestamp</summary><ol>{transcript.sentences.map(s => <li key={s.id}>{s.start.toFixed(2)}–{s.end.toFixed(2)} · {s.text}</li>)}</ol></details></section>}
    {transcript && <p><Link href={`/projects/${id}/evaluate`}>Anotasi kualitas sumber</Link></p>}
    <ul>{(project.outputs ?? []).map(output => <li key={output.id}><Link href={`/outputs/${output.id}`}>{output.mode} · {output.status}</Link></li>)}</ul><h2>Tambah output</h2><CreateForm projectId={id} /></>;
}
