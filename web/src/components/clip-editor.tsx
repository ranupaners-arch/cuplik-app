"use client";
import { Badge, Button } from "@mantine/core";

import { useState } from "react";
import { patch, post, type Clip, type Detail } from "@/lib/api";
import { ClipControls, platformLabels, profile, type ClipControlsValue } from "@/components/clip-controls";

type Perform = (action: () => Promise<unknown>) => Promise<void>;
const qcLabels: Record<string, string> = { video_stream: "Gambar video", audio_stream: "Audio", duration: "Durasi edit", dimensions: "Resolusi", black_frames: "Frame hitam", silence: "Jeda hening", loudness: "Volume suara", true_peak: "Puncak audio", caption_safe_area: "Area aman caption", platform_format: "Format platform tujuan" };

export function ClipEditor({ clip, data, disabled, perform }: { clip: Clip; data: Detail; disabled: boolean; perform: Perform }) {
  const sentences = data.transcript?.sentences.filter(s => s.start < clip.end_s && s.end > clip.start_s) ?? [];
  const words = new Map(data.transcript?.words?.map(w => [w.id, w]));
  const [choice, setChoice] = useState(clip.hook_choice);
  const [titleChoice, setTitleChoice] = useState(clip.title_choice);
  const [start, setStart] = useState(clip.start_s);
  const [end, setEnd] = useState(clip.end_s);
  const [controls, setControls] = useState<ClipControlsValue>(() => ({
    purpose: clip.purpose as ClipControlsValue["purpose"], platform: clip.platform as ClipControlsValue["platform"],
    layout: (clip.layout === "center" ? "auto" : clip.layout) as ClipControlsValue["layout"],
    captions: clip.captions, retention: { ...profile("discovery", true), ...clip.retention },
    visual_focus: { mode: "safe", ...clip.visual_focus } as ClipControlsValue["visual_focus"],
  }));
  const [texts, setTexts] = useState<Record<string, string>>({ ...clip.caption_overrides });
  const [ratingNote, setRatingNote] = useState(clip.rating_note);
  const [added, setAdded] = useState<string[]>([]);
  const checks = (clip.qc.checks ?? {}) as Record<string, boolean>;
  const levels = (clip.qc.loudness ?? {}) as Record<string, number>;
  const edit = (clip.qc.retention ?? {}) as { warnings?: string[] };
  const delivery = (clip.qc.delivery ?? {}) as { notes?: string[] };
  const corrections = Object.entries(texts).filter(([id, text]) => words.has(id) && words.get(id)!.text !== text && text.trim() && !/\s/.test(text));

  return <article data-testid="clip-result" className="clip-workspace">
    <h2>#{clip.rank} {clip.titles[clip.title_choice]}</h2>
    <p><Badge component="span" className="score-badge" color={clip.score >= 8 ? "teal" : clip.score >= 5 ? "turmeric" : "gray"} variant="light">Skor editorial: {clip.score.toFixed(1)}</Badge> · {clip.start_s.toFixed(2)}–{clip.end_s.toFixed(2)} detik</p>
    <p>{platformLabels[clip.platform as keyof typeof platformLabels]} · {clip.purpose === "tutorial" ? "Tutorial" : "Jangkauan"}</p>
    <p>{clip.reason}</p>
    {clip.selection.boundary_edited === true && <p>Batas diubah pengguna. Skor dan alasan di atas berasal dari pilihan awal.</p>}
    <details><summary>Rincian skor</summary><pre>{JSON.stringify(clip.rubric, null, 2)}</pre><p>Catatan urutan: {String(clip.selection.rerank_note ?? "")}</p><p>Ketepatan batas: {clip.selection.boundary_precision === "word" ? "timestamp per kata" : "timestamp per kalimat"}</p></details>
    <div className="clip-layout"><div className="clip-preview">
    {clip.file_url && !clip.needs_render && <><video className="clip-player" data-portrait={Number(clip.qc.width) < Number(clip.qc.height)} controls playsInline preload="metadata" width={960} poster={clip.thumbnail_url ? `${clip.thumbnail_url}?v=${clip.render_fingerprint}` : undefined} src={`${clip.file_url}?v=${clip.render_fingerprint}`} /><a href={clip.file_url} download>Unduh klip MP4</a>{clip.thumbnail_url && <p><a href={clip.thumbnail_url} download>Unduh thumbnail</a></p>}</>}
    {clip.needs_render && <><p>Pengaturan berubah; video perlu dirender ulang.</p><Button type="submit" disabled={disabled} onClick={() => perform(() => post(`/clips/${clip.id}/render`))}>Perbarui video klip</Button></>}
    </div><div className="clip-settings">
    {clip.qc.passed === false && <p className="error">Pemeriksaan kualitas membutuhkan tinjauan. Periksa rincian sebelum menggunakan hasil.</p>}
    {Object.keys(checks).length > 0 && <details><summary>Pemeriksaan kualitas video</summary><ul>{Object.entries(checks).map(([key, passed]) => <li key={key}>{qcLabels[key] ?? key}: {passed ? "lolos" : "perlu ditinjau"}</li>)}</ul><p>Durasi hasil: {Number(clip.qc.duration_s).toFixed(2)} detik.</p><p>Loudness: {levels.input_i == null ? "tidak terukur" : `${Number(levels.input_i).toFixed(1)} LUFS`} · Puncak: {levels.input_tp == null ? "tidak terukur" : `${Number(levels.input_tp).toFixed(1)} dBTP`}.</p><p>Waktu caption: {clip.qc.caption_timing === "word" ? "timestamp per kata" : "mengandung perkiraan waktu"}.</p>{edit.warnings?.map((warning, index) => <p key={index}>{warning}</p>)}</details>}
    {clip.qc.width != null && clip.qc.height != null && <p>Resolusi: {String(clip.qc.width)} × {String(clip.qc.height)} · Caption frasa pendek.</p>}
    {delivery.notes?.map((note, index) => <p key={index}>{note}</p>)}
    <details><summary>Edit judul, hook, dan caption</summary><form onSubmit={e => {
      e.preventDefault(); void perform(async () => {
        await patch(`/clips/${clip.id}`, { title_choice: titleChoice, hook_choice: choice, ...controls, caption_overrides: texts,
          ...(start !== clip.start_s || end !== clip.end_s ? { start_s: start, end_s: end } : {}) });
        await post(`/clips/${clip.id}/render`);
      });
    }}><fieldset disabled={disabled}><legend>Pengaturan klip #{clip.rank}</legend>
      <label>Judul<select value={titleChoice} onChange={e => setTitleChoice(Number(e.target.value))}>{clip.titles.map((title, i) => <option key={i} value={i}>{title}</option>)}</select></label>
      <label>Hook<select value={choice} onChange={e => setChoice(Number(e.target.value))}>{clip.hook_options.map((hook, i) => <option key={i} value={i}>{hook}</option>)}</select></label>
      <label>Awal klip (detik)<input type="number" step="any" min={0} max={data.project.duration_s} value={start} required onChange={e => setStart(Number(e.target.value))} /></label>
      <label>Akhir klip (detik)<input type="number" step="any" min={0.01} max={data.project.duration_s} value={end} required onChange={e => setEnd(Number(e.target.value))} /></label>
      <p>Batas akan ditempel ke timestamp kata terdekat. Jika waktu kata tidak tersedia, batas memakai kalimat. Durasi hasil trim 1–180 detik.</p>
      <ClipControls value={controls} onChange={setControls} />
      <p>Koreksi kata mempertahankan waktu ucapan. Ubah sesuai audio agar subtitle tetap akurat.</p>
      {sentences.map(sentence => {
        const visible = (sentence.word_ids ?? []).map(id => words.get(id)).filter(w => w && w.start < clip.end_s && w.end > clip.start_s);
        const legacy = texts[sentence.id];
        if (!visible.length || (legacy != null && legacy.split(/\s+/).length !== visible.length)) {
          return <div key={sentence.id}><label>Caption {sentence.id}<textarea value={legacy ?? sentence.text} required maxLength={4000} onChange={e => setTexts({ ...texts, [sentence.id]: e.target.value })} /></label><small>Waktu per kata diperkirakan untuk kalimat ini.</small>{visible.length > 0 && <Button type="button" onClick={() => { const next = { ...texts }; delete next[sentence.id]; setTexts(next); }}>Pulihkan kata asli {sentence.id}</Button>}</div>;
        }
        return <fieldset key={sentence.id}><legend>Kata pada {sentence.id}</legend>{visible.map((word, index) => {
          if (!word) return null;
          return <label key={word.id}>Kata {word.id} ({word.start.toFixed(2)}–{word.end.toFixed(2)} dtk)<input value={texts[word.id] ?? legacy?.split(/\s+/)[index] ?? word.text} required maxLength={500} pattern="\S+" onChange={e => {
            const next = { ...texts };
            if (legacy != null) { visible.forEach((w, i) => { if (w) next[w.id] = next[w.id] ?? legacy.split(/\s+/)[i]; }); delete next[sentence.id]; }
            next[word.id] = e.target.value; setTexts(next);
          }} /></label>;
        })}</fieldset>;
      })}
      <Button type="submit" className="studio-primary">Simpan dan render ulang klip</Button>
    </fieldset></form></details>
    {corrections.length > 0 && <details><summary>Tambahkan koreksi kata ke glosarium</summary><p>Berlaku untuk transkripsi proyek baru; transkrip yang sudah selesai tetap tersimpan.</p>{corrections.map(([id, text]) => <p key={id}><Button type="submit" disabled={disabled || added.includes(id)} onClick={() => perform(async () => { await post("/glossary", { wrong: words.get(id)!.text, correct: text }); setAdded(value => [...value, id]); })}>Simpan {words.get(id)!.text} → {text} ke glosarium</Button>{added.includes(id) && <span role="status">Tersimpan.</span>}</p>)}</details>}
    <fieldset disabled={disabled}><legend>Penilaian klip #{clip.rank}</legend><div className="row"><Button type="submit" aria-pressed={clip.rating === "up"} onClick={() => perform(() => patch(`/clips/${clip.id}`, { rating: clip.rating === "up" ? null : "up", rating_note: ratingNote }))}>Suka</Button><Button type="submit" aria-pressed={clip.rating === "down"} onClick={() => perform(() => patch(`/clips/${clip.id}`, { rating: clip.rating === "down" ? null : "down", rating_note: ratingNote }))}>Tidak suka</Button></div>
      <label>Catatan penilaian<textarea value={ratingNote} maxLength={1000} onChange={e => setRatingNote(e.target.value)} /></label><Button type="submit" onClick={() => perform(() => patch(`/clips/${clip.id}`, { rating_note: ratingNote }))}>Simpan catatan penilaian</Button>
      <small>Maksimal tiga contoh yang disukai dengan tujuan serupa menjadi masukan pemilihan berikutnya.</small>
    </fieldset>
    </div></div>
  </article>;
}
