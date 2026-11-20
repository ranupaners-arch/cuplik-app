"use client";
import { Button } from "@mantine/core";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { api, post, type AnnotationDocument, type AnnotationRange, type AnnotationView, type Project } from "@/lib/api";

type Group = "ranges" | "required_chapters" | "required_specs";

export function AnnotationPage({ id }: { id: string }) {
  const prefix = useId();
  const video = useRef<HTMLVideoElement>(null);
  const errorSummary = useRef<HTMLParagraphElement>(null);
  const [mode, setMode] = useState<"clips" | "condense">("clips");
  const [view, setView] = useState<AnnotationView | null>(null);
  const [document, setDocument] = useState<AnnotationDocument | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [revision, setRevision] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [sourceMissing, setSourceMissing] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [outputId, setOutputId] = useState("");
  useEffect(() => {
    let active = true;
    setError(""); setView(null); setDocument(null); setDirty(false); setOutputId("");
    Promise.all([api<AnnotationView>(`/projects/${id}/annotations/${mode}`), api<Project>(`/projects/${id}`)])
      .then(([value, source]) => {
        if (!active) return;
        setView(value); setProject(source);
        setDocument(value.stale ? { ...value.document, status: "draft", review_confirmed: false } : value.document);
      }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [id, mode, revision]);
  useEffect(() => { if (error) errorSummary.current?.focus(); }, [error]);
  useEffect(() => {
    if (!preparing) return;
    let active = true;
    const timer = setInterval(() => {
      api<Project>(`/projects/${id}`).then(source => {
        if (!active) return;
        if (source.ingest_status === "done") {
          setPreparing(false); setSourceMissing(false); video.current?.load();
          setMessage("Sumber siap. Jika isinya berubah, muat ulang anotasi sebelum menyimpan.");
        } else if (source.ingest_status === "failed" || source.transcript_status === "failed") {
          setPreparing(false); setError(source.error ?? "Penyiapan sumber gagal; lihat halaman proyek.");
        }
      }).catch(e => { if (active) { setPreparing(false); setError(e.message); } });
    }, 1500);
    return () => { active = false; clearInterval(timer); };
  }, [id, preparing]);

  const change = (value: Partial<AnnotationDocument>) => { setDocument(current => current ? { ...current, ...value } : current); setDirty(true); setMessage(""); setError(""); };
  function rangeChange(group: Group, index: number, value: Partial<AnnotationRange>) {
    if (document) change({ [group]: document[group].map((r, i) => i === index ? { ...r, ...value } : r) });
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!document || !view) return;
    if (!dirty) { setMessage("Tidak ada perubahan baru."); return; }
    setBusy(true); setError("");
    try {
      const result = await api<AnnotationView>(`/projects/${id}/annotations/${mode}`, { method: "PUT", body: JSON.stringify({ expected_revision: view.revision, source_fingerprint: view.source_fingerprint, transcript_fingerprint: view.transcript_fingerprint, document }) });
      setView(result); setDocument(result.document); setDirty(false); setMessage(`Anotasi tersimpan, revisi ${result.revision}.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  function rangeFields(group: Group, title: string) {
    if (!document || !view) return null;
    return <fieldset><legend>{title}</legend>
      {document[group].map((range, index) => {
        const key = `${prefix}-${group}-${index}`;
        return <fieldset key={key}><legend>{title} #{index + 1}</legend>
          <label htmlFor={`${key}-start`}>Awal {title.toLowerCase()} #{index + 1} (detik)</label>
          <input id={`${key}-start`} name={`${group}.${index}.start_s`} type="number" min={0} max={view.duration_s} step="any" required value={range.start_s} onChange={e => rangeChange(group, index, { start_s: Number(e.target.value) })} />
          <Button type="button" onClick={() => rangeChange(group, index, { start_s: video.current?.currentTime ?? range.start_s })}>Gunakan waktu putar sebagai awal #{index + 1}</Button>
          <label htmlFor={`${key}-end`}>Akhir {title.toLowerCase()} #{index + 1} (detik)</label>
          <input id={`${key}-end`} name={`${group}.${index}.end_s`} type="number" min={0.001} max={view.duration_s} step="any" required value={range.end_s} onChange={e => rangeChange(group, index, { end_s: Number(e.target.value) })} />
          <Button type="button" onClick={() => rangeChange(group, index, { end_s: video.current?.currentTime ?? range.end_s })}>Gunakan waktu putar sebagai akhir #{index + 1}</Button>
          <label htmlFor={`${key}-label`}>Label {title.toLowerCase()} #{index + 1}{mode === "condense" && document.status === "reviewed" ? " (wajib)" : ""}</label>
          <input id={`${key}-label`} name={`${group}.${index}.label`} maxLength={300} required={mode === "condense" && document.status === "reviewed"} value={range.label ?? ""} onChange={e => rangeChange(group, index, { label: e.target.value })} />
          <Button type="button" onClick={() => change({ [group]: document[group].filter((_, i) => i !== index) })}>Hapus {title.toLowerCase()} #{index + 1}</Button>
        </fieldset>;
      })}
      <Button type="button" disabled={document[group].length >= 100} onClick={() => change({ [group]: [...document[group], { start_s: 0, end_s: Math.min(1, view.duration_s), label: "" }] })}>Tambah {title.toLowerCase()}</Button>
    </fieldset>;
  }

  return <>
    <h1>Anotasi kualitas sumber</h1><p><Link href={`/projects/${id}`}>Kembali ke proyek</Link></p>
    <p>Tonton sumber dan tandai momen atau langkah yang wajib dipertahankan. Form ini tidak mengisi label dari prediksi AI.</p>
    {error && <p role="alert" tabIndex={-1} ref={errorSummary} className="error">{error}</p>}
    <p role="status">{message}</p>
    <Button type="button" disabled={busy || dirty} onClick={() => setRevision(value => value + 1)}>Muat ulang anotasi</Button>
    {view && document && <>
      <p>{view.dataset_kind === "synthetic" ? "Sumber demo sintetis; hasilnya tidak masuk ukuran kualitas manusia." : "Anotasi sumber pengguna."} Revisi tersimpan: {view.revision}.</p>
      {view.stale && <p>Isi sumber/transkrip berubah. Tinjau ulang sebelum menyimpan sebagai selesai.</p>}
      {view.predictions_exist && <p>Prediksi sudah tersedia. Perubahan label berikutnya dicatat sebagai assisted dan tidak dihitung sebagai anotasi independen.</p>}
      <video ref={video} controls preload="metadata" width={960} height={540} src={`/api/projects/${id}/source`} onError={() => setSourceMissing(true)}>
        <track kind="captions" src={`/api/projects/${id}/transcript.vtt`} srcLang={view.language} label="Transkrip sumber, perlu ditinjau" />
      </video>
      {sourceMissing && <p>Video belum dapat dibuka. <Button type="button" disabled={preparing || busy} onClick={async () => { setError(""); try { await post(`/projects/${id}/prepare-source`); setPreparing(true); setMessage("Sumber sedang disiapkan; anotasi lokal tetap tersedia."); } catch (e) { setError((e as Error).message); } }}>Siapkan ulang sumber</Button></p>}
      <p><a href={`/api/projects/${id}/source`} download="source.mp4">Unduh sumber untuk paket evaluasi</a></p>
      <fieldset disabled={busy || dirty}><legend>Mode anotasi</legend>{(["clips", "condense"] as const).map(value => <div key={value}><input id={`${prefix}-mode-${value}`} type="radio" name="annotation-mode" value={value} checked={mode === value} onChange={() => setMode(value)} /><label htmlFor={`${prefix}-mode-${value}`}>{value === "clips" ? "Label Klip" : "Label Ringkas"}</label></div>)}</fieldset>
      {dirty && <p>Perubahan belum disimpan. Simpan atau batalkan sebelum mengganti mode.</p>}
      <form method="post" onSubmit={save} aria-label="Form anotasi manusia"><fieldset disabled={busy}><legend>Penilaian manual</legend>
        <fieldset><legend>Status anotasi</legend>{(["draft", "reviewed"] as const).map(status => <div key={status}><input type="radio" id={`${prefix}-${status}`} name="annotation-status" value={status} checked={document.status === status} onChange={() => change({ status, review_confirmed: false })} /><label htmlFor={`${prefix}-${status}`}>{status === "draft" ? "Draft" : "Sudah ditinjau"}</label></div>)}</fieldset>
        <label htmlFor={`${prefix}-annotator`}>Nama peninjau{document.status === "reviewed" ? " (wajib)" : ""}</label>
        <input id={`${prefix}-annotator`} name="annotator" autoComplete="name" maxLength={120} required={document.status === "reviewed"} value={document.annotator} onChange={e => change({ annotator: e.target.value })} />
        {mode === "clips" ? rangeFields("ranges", "Momen") : <>{rangeFields("required_chapters", "Bab wajib")}{rangeFields("required_specs", "Spesifikasi wajib")}
          <label htmlFor={`${prefix}-target`}>Target evaluasi Ringkas (detik)</label><input id={`${prefix}-target`} name="target_seconds" type="number" min={3} max={3600} required value={document.settings.target_seconds} onChange={e => change({ settings: { ...document.settings, target_seconds: Number(e.target.value) } })} /></>}
        <label htmlFor={`${prefix}-note`}>Catatan peninjau</label><textarea id={`${prefix}-note`} name="note" maxLength={4000} value={document.note} onChange={e => change({ note: e.target.value })} />
        <div><input id={`${prefix}-independent`} name="independent" type="checkbox" checked={document.independent} disabled={view.predictions_exist} onChange={e => change({ independent: e.target.checked })} /><label htmlFor={`${prefix}-independent`}>Label dibuat tanpa melihat prediksi</label></div>
        <div><input id={`${prefix}-confirmed`} name="review_confirmed" type="checkbox" required={document.status === "reviewed"} checked={document.review_confirmed} onChange={e => change({ review_confirmed: e.target.checked })} /><label htmlFor={`${prefix}-confirmed`}>Saya sudah menonton dan meninjau rentang ini secara manual{document.status === "reviewed" ? " (wajib)" : ""}</label></div>
        <Button type="submit">Simpan anotasi</Button><Button type="button" disabled={!dirty} onClick={() => { setDocument(view.stale ? { ...view.document, status: "draft", review_confirmed: false } : view.document); setDirty(false); setError(""); }}>Batalkan perubahan</Button>
      </fieldset></form>
      {!dirty && !view.stale && view.document.status === "reviewed" && <section><h2>Paket evaluasi</h2><p>Simpan sumber sebagai source.mp4 di folder paket setelah diekstrak. Draft, assisted, demo, dan prediksi mock tidak menjadi ukuran kualitas independen.</p>
        <label htmlFor={`${prefix}-prediction`}>Prediksi pembanding (opsional)</label><select id={`${prefix}-prediction`} value={outputId} onChange={e => setOutputId(e.target.value)}><option value="">Label saja</option>{project?.outputs?.filter(output => output.mode === mode && output.status === "done" && output.provenance?.source_sha256 === view.source_fingerprint && output.provenance?.transcript_sha256 === view.transcript_fingerprint).map(output => <option key={output.id} value={output.id}>{output.mode} · {output.id?.slice(0, 8)}</option>)}</select>
        <p><a href={`/api/projects/${id}/annotations/${mode}/export.zip${outputId ? `?output_id=${encodeURIComponent(outputId)}` : ""}`} download>Unduh paket evaluasi (ZIP)</a></p>
      </section>}
    </>}
  </>;
}
