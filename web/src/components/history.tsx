"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Project } from "@/lib/api";

export function History() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api<Project[]>("/projects").then(setProjects).catch(e => setError(e.message)); }, []);
  return <>{error && <p role="alert" className="error">{error}</p>}{!projects && !error && <p>Memuat riwayat…</p>}{projects?.length === 0 && <p>Belum ada proyek.</p>}{projects?.map(project => <article key={project.id}><h2><Link href={`/projects/${project.id}`}>{project.title}</Link></h2><p>{project.source_kind} · sumber {project.ingest_status} · transkrip {project.transcript_status}</p>{project.error && <p className="error">{project.error}</p>}<ul>{(project.outputs ?? []).map(output => <li key={output.id}><Link href={`/outputs/${output.id}`}>{output.mode} · {output.status}</Link></li>)}</ul></article>)}</>;
}
