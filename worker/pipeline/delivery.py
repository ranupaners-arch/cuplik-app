"""Delivery intent is separate from how the subject is framed."""


def effective_layout(clip):
    if clip.platform != "youtube":
        return "portrait"
    if clip.purpose == "tutorial" and clip.layout in ("auto", "center"):
        return "source"
    return "auto" if clip.layout == "center" else clip.layout


def inspect_delivery(clip, framing, duration):
    short = clip.platform != "youtube"
    valid = not short or (framing.width * 16 == framing.height * 9 and duration <= 180.001)
    notes = []
    if (
        short
        and framing.content_kind == "screen_or_slides"
        and framing.source_width > framing.source_height
    ):
        notes.append(
            "Rekaman layar lebar dimuat utuh dalam bingkai vertikal. Periksa keterbacaan menu/nilai; pilih video YouTube dengan rasio sumber jika detail terlalu kecil."
        )
    if clip.purpose == "tutorial":
        notes.append(
            "Periksa urutan langkah dan detail demonstrasi. Kelengkapan tutorial belum diverifikasi otomatis."
        )
    return {
        "purpose": clip.purpose,
        "platform": clip.platform,
        "format_valid": valid,
        "effective_layout": effective_layout(clip),
        "notes": notes,
        "scope": "Rasio dan batas 180 detik profil Cuplik; bukan jaminan distribusi atau seluruh syarat platform.",
    }
