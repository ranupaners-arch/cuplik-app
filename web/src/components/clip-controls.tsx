"use client";

import type { Settings } from "@/lib/api";

export type Retention = NonNullable<Settings["retention"]>;
export type ClipControlsValue = {
  purpose: "tutorial" | "discovery";
  platform: "youtube" | "youtube_shorts" | "tiktok" | "instagram";
  layout: "auto" | "source" | "portrait";
  captions: boolean;
  retention: Retention;
};

export const retentionLabels: Record<keyof Retention, string> = {
  shorten_pauses: "Pendekkan jeda", remove_fillers: "Hapus pengisi yang berdiri sendiri",
  zoom: "Zoom halus pada pembicara", emphasis: "Tekankan kata pilihan",
  cold_open: "Cold open jika tersedia", karaoke: "Sorot kata yang sedang diucapkan",
  keyword_highlights: "Sorot kata kunci", emoji: "Emoji jika sesuai",
};

export function profile(purpose: ClipControlsValue["purpose"], karaoke = false): Retention {
  return { shorten_pauses: purpose !== "tutorial", remove_fillers: purpose !== "tutorial",
    zoom: purpose !== "tutorial", emphasis: purpose !== "tutorial", cold_open: false,
    karaoke, keyword_highlights: karaoke, emoji: false };
}

export function controlValues(settings: Partial<Settings>): ClipControlsValue {
  const purpose = settings.purpose ?? "tutorial";
  return { purpose, platform: settings.platform ?? "youtube", layout: settings.layout ?? "auto",
    captions: settings.captions ?? true, retention: { ...profile(purpose), ...settings.retention } };
}

export const platformLabels = { youtube: "Video YouTube / rasio sumber", youtube_shorts: "YouTube Shorts", tiktok: "TikTok", instagram: "Instagram Reels" };

export function ClipControls({ value, onChange }: { value: ClipControlsValue; onChange: (value: ClipControlsValue) => void }) {
  return <>
    <label>Tujuan klip<select value={value.purpose} onChange={e => {
      const purpose = e.target.value as ClipControlsValue["purpose"];
      onChange({ ...value, purpose, retention: profile(purpose, value.retention.karaoke) });
    }}><option value="tutorial">Tutorial: jaga langkah demonstrasi</option><option value="discovery">Jangkauan: satu ide dan payoff</option></select></label>
    <label>Platform tujuan<select value={value.platform} onChange={e => {
      const platform = e.target.value as ClipControlsValue["platform"];
      onChange({ ...value, platform, layout: platform !== "youtube" && value.layout === "source" ? "auto" : value.layout });
    }}>{Object.entries(platformLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
    <label>Pembingkaian klip<select value={value.layout} onChange={e => onChange({ ...value, layout: e.target.value as ClipControlsValue["layout"] })}>
      <option value="auto">Otomatis mengikuti tujuan dan isi video</option>
      {value.platform === "youtube" && <option value="source">Bingkai sumber utuh</option>}
      <option value="portrait">Vertikal 9:16, pertahankan isi</option>
    </select></label>
    <p>{value.platform !== "youtube" ? "Keluaran memakai kanvas vertikal. Rekaman layar lebar tetap dimuat utuh bila crop belum aman; periksa keterbacaan detail pada preview." : value.purpose === "tutorial" ? "Otomatis menjaga bingkai sumber untuk tutorial. Pilih vertikal jika detail tugas tetap terbaca." : "Otomatis mempertahankan konteks dan memakai crop pembicara hanya bila aman."}</p>
    <label><input type="checkbox" checked={value.captions} onChange={e => onChange({ ...value, captions: e.target.checked })} />Tampilkan caption</label>
    <label>Preset caption<select value={value.retention.karaoke ? "karaoke" : "compact"} onChange={e => onChange({ ...value, retention: { ...value.retention, karaoke: e.target.value === "karaoke", keyword_highlights: e.target.value === "karaoke" } })}><option value="compact">Frasa ringkas</option><option value="karaoke">Frasa ringkas dengan karaoke</option></select></label>
    <details><summary>Ritme video dan sorotan caption</summary>
      <p>{value.purpose === "tutorial" ? "Profil tutorial menjaga jeda dan urutan asli. Aktifkan teknik berikut hanya jika langkah demonstrasi tetap utuh." : "Atur teknik per klip dan periksa hasilnya pada preview."}</p>
      {Object.entries(retentionLabels).map(([key, label]) => <label key={key}><input type="checkbox" checked={value.retention[key as keyof Retention] ?? false} onChange={e => onChange({ ...value, retention: { ...value.retention, [key]: e.target.checked } })} />{label}</label>)}
    </details>
  </>;
}
