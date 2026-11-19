"use client";

import { useId } from "react";
import type { Settings } from "@/lib/api";

export function CondenseVisionControls({ value, onChange }: { value: NonNullable<Settings["condense_vision"]>; onChange: (value: NonNullable<Settings["condense_vision"]>) => void }) {
  const id = useId();
  return <fieldset><legend>Analisis Ringkas</legend>
    <p id={`${id}-help`}>Vision mengirim sampel gambar ke provider yang dipilih di server. Jumlah frame diperiksa sebelum panggilan LLM; outline tetap ditinjau sebelum render.</p>
    <div><input id={`${id}-off`} type="radio" name={`${id}-mode`} checked={!value.enabled} onChange={() => onChange({ ...value, enabled: false })} aria-describedby={`${id}-help`} /><label htmlFor={`${id}-off`}>Transkrip saja</label></div>
    <div><input id={`${id}-on`} type="radio" name={`${id}-mode`} checked={value.enabled ?? false} onChange={() => onChange({ ...value, enabled: true })} aria-describedby={`${id}-help`} /><label htmlFor={`${id}-on`}>Transkrip dan frame (vision)</label></div>
    <fieldset disabled={!value.enabled}><legend>Sampling frame</legend>
      <div><input id={`${id}-screen`} name="screen_tutorial" type="checkbox" checked={value.screen_tutorial ?? false} onChange={e => onChange({ ...value, screen_tutorial: e.target.checked })} /><label htmlFor={`${id}-screen`}>Tutorial layar: gambar hingga 1024 px</label></div>
      <label htmlFor={`${id}-budget`}>Batas frame vision</label><input id={`${id}-budget`} name="max_frames" type="number" min={16} max={4096} step={1} required value={value.max_frames ?? 720} onChange={e => onChange({ ...value, max_frames: Number(e.target.value) })} />
      <p>Frame visual diambil per 5 detik, frame bicara per 15 detik, minimal satu per beat. Bila melebihi batas, proses berhenti untuk penyesuaian. Mode mock memakai deskripsi fixture.</p>
    </fieldset>
  </fieldset>;
}
