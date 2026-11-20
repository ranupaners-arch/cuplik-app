"use client";

import { useId } from "react";
import type { Settings } from "@/lib/api";

export function CondenseTimingControls({ value, onChange }: { value: Partial<Settings>; onChange: (value: Partial<Settings>) => void }) {
  const id = useId();
  return <fieldset><legend>Pengolahan Ringkas</legend>
    <label htmlFor={`${id}-speech`}>Batas kecepatan narasi</label><input id={`${id}-speech`} name="max_speech_speed" type="number" min={1} max={1.25} step={.01} required value={value.max_speech_speed ?? 1.15} onChange={e => onChange({ max_speech_speed: Number(e.target.value) })} />
    <div><input id={`${id}-enabled`} name="timelapse_enabled" type="checkbox" checked={value.timelapse_enabled ?? false} onChange={e => onChange({ timelapse_enabled: e.target.checked })} aria-describedby={`${id}-help`} /><label htmlFor={`${id}-enabled`}>Aktifkan timelapse visual yang sudah ditinjau</label></div>
    <label htmlFor={`${id}-visual`}>Batas kecepatan timelapse</label><input id={`${id}-visual`} name="max_visual_speed" type="number" min={2} max={8} step={.1} required disabled={!value.timelapse_enabled} value={value.max_visual_speed ?? 8} onChange={e => onChange({ max_visual_speed: Number(e.target.value) })} />
    <p id={`${id}-help`}>Timelapse 2–8× hanya untuk beat visual manual/idle/repeat yang disetujui per beat. Audio bagian tersebut diganti hening dan video diberi penanda kecepatan. Instruksi, spesifikasi, serta hasil memakai batas aman.</p>
    <div><input id={`${id}-coherence`} name="coherence_enabled" type="checkbox" checked={value.coherence_enabled ?? false} onChange={e => onChange({ coherence_enabled: e.target.checked })} aria-describedby={`${id}-coherence-help`} /><label htmlFor={`${id}-coherence`}>Periksa koherensi sebelum render</label></div>
    <p id={`${id}-coherence-help`}>LLM memeriksa konteks naskah terpilih, maksimal dua putaran per persetujuan. Jika pilihan video berubah atau masalah belum selesai, proses kembali ke tinjauan. Provider mock hanya menguji alur.</p>
    <div><input id={`${id}-cards`} name="chapter_cards" type="checkbox" checked={value.chapter_cards ?? false} onChange={e => onChange({ chapter_cards: e.target.checked })} /><label htmlFor={`${id}-cards`}>Tampilkan judul bab selama dua detik</label></div>
    <p>Judul tampil sebagai overlay kecil di awal bab, tanpa menambah durasi atau mengubah audio.</p>
  </fieldset>;
}
