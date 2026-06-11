"""Lightweight localization for recommendation card content (en/es/pt).

The scoring layers emit a small, finite set of English phrases (why-it-fits, tradeoffs,
route notes, food-safety notes). We localize them by template + fragment replacement so a
Spanish/Portuguese fan reads a Spanish/Portuguese card, not an English one. Unknown text
falls through unchanged (never blocks a response).
"""
from __future__ import annotations
import re

# fixed phrase -> {es, pt}
FIXED = {
    "a neighborhood favorite, not a chain": {"es": "un favorito del barrio, no una cadena", "pt": "um favorito do bairro, não uma rede"},
    "a historic local spot": {"es": "un lugar local histórico", "pt": "um lugar local histórico"},
    "a cultural local spot": {"es": "un lugar local cultural", "pt": "um lugar local cultural"},
    "open late for the post-match wave": {"es": "abierto hasta tarde para después del partido", "pt": "aberto até tarde para o pós-jogo"},
    "easy from VTA/Caltrain": {"es": "fácil desde VTA/Caltrain", "pt": "fácil de VTA/Caltrain"},
    "fewer reviews than a tourist magnet, but stronger local signal": {"es": "menos reseñas que un lugar turístico, pero más señal local", "pt": "menos avaliações que um ponto turístico, mas mais sinal local"},
    "convenient but less local": {"es": "conveniente pero menos local", "pt": "conveniente, mas menos local"},
    "well-rated and reliable": {"es": "bien valorado y confiable", "pt": "bem avaliado e confiável"},
    "no specific allergen info — call ahead": {"es": "sin info específica de alérgenos — llama antes", "pt": "sem info específica de alérgenos — ligue antes"},
}
# Review-derived DEPTH phrases (why_locals_love_it praise labels + local_character cue labels +
# narrative prefixes). These were English-only inside es/pt cards — a visible flaw for the World
# Cup's international-fan audience. Localized here so the whole card reads in the fan's language.
# (Verbatim review_quote and proper-noun transit names are intentionally NOT translated.)
DEPTH = {
    # _PRAISE_TERMS labels (why_locals_love_it)
    "literally called a hidden gem": {"es": "lo llaman literalmente una joya escondida", "pt": "chamado literalmente de joia escondida"},
    "authentic / traditional cooking": {"es": "cocina auténtica / tradicional", "pt": "cozinha autêntica / tradicional"},
    "homemade / home-style taste": {"es": "sabor casero / de casa", "pt": "sabor caseiro / de casa"},
    "generous portions": {"es": "porciones generosas", "pt": "porções generosas"},
    "a 'best-in-area' / go-to for regulars": {"es": "un 'mejor de la zona' / favorito de los habituales", "pt": "um 'melhor da região' / preferido dos frequentadores"},
    "great value": {"es": "excelente relación calidad-precio", "pt": "ótimo custo-benefício"},
    "a cozy local atmosphere": {"es": "un ambiente local acogedor", "pt": "um ambiente local aconchegante"},
    "food people call delicious": {"es": "comida que la gente llama deliciosa", "pt": "comida que as pessoas chamam de deliciosa"},
    "friendly, welcoming service": {"es": "servicio amable y acogedor", "pt": "atendimento simpático e acolhedor"},
    "fresh ingredients": {"es": "ingredientes frescos", "pt": "ingredientes frescos"},
    # _local_character narrative prefix + cue labels + chain/no-text narratives
    "What a national chain can't replicate here: ": {"es": "Lo que una cadena nacional no puede replicar aquí: ", "pt": "O que uma rede nacional não consegue replicar aqui: "},
    "homestyle": {"es": "estilo casero", "pt": "estilo caseiro"},
    "authentic, traditional cooking — not a standardized chain menu": {"es": "cocina auténtica y tradicional — no un menú de cadena estandarizado", "pt": "cozinha autêntica e tradicional — não um cardápio de rede padronizado"},
    "cooked fresh": {"es": "cocinado al momento", "pt": "feito na hora"},
    "made-to-order, not pre-made and held under a heat lamp": {"es": "hecho al momento, no precocinado bajo una lámpara de calor", "pt": "feito na hora, não pré-preparado sob lâmpada de calor"},
    "house-made": {"es": "hecho en casa", "pt": "feito na casa"},
    "scratch-made / family recipes a chain can't replicate": {"es": "hecho desde cero / recetas familiares que una cadena no puede replicar", "pt": "feito do zero / receitas de família que uma rede não replica"},
    "flavorful": {"es": "lleno de sabor", "pt": "cheio de sabor"},
    "boldly spiced, real flavor (not dialed-down for the masses)": {"es": "bien condimentado, sabor de verdad (no suavizado para las masas)", "pt": "bem temperado, sabor de verdade (não suavizado para as massas)"},
    "traditional cooking methods": {"es": "métodos de cocina tradicionales", "pt": "métodos de cozinha tradicionais"},
    "fresh produce": {"es": "productos frescos", "pt": "produtos frescos"},
    "fresh / made-daily, not frozen-and-reheated": {"es": "fresco / hecho a diario, no congelado y recalentado", "pt": "fresco / feito diariamente, não congelado e requentado"},
    "family-owned & operated": {"es": "de propiedad y gestión familiar", "pt": "de propriedade e gestão familiar"},
    "a longtime neighborhood institution": {"es": "una institución del barrio de toda la vida", "pt": "uma instituição do bairro de longa data"},
    "an unassuming hole-in-the-wall locals seek out": {"es": "un local sencillo y escondido que buscan los del lugar", "pt": "um lugar simples e escondido que os locais procuram"},
    "a local secret kept by regulars": {"es": "un secreto local guardado por los habituales", "pt": "um segredo local guardado pelos frequentadores"},
    "This is a national/regional chain — a standardized, consistent menu. It's the kind of known-quantity option FanFlow exists to weigh AGAINST the independent locals.":
        {"es": "Es una cadena nacional/regional — un menú estandarizado y consistente. Es justo el tipo de opción conocida que FanFlow existe para comparar FRENTE a los locales independientes.",
         "pt": "É uma rede nacional/regional — um cardápio padronizado e consistente. É justamente o tipo de opção conhecida que o FanFlow existe para comparar EM RELAÇÃO aos locais independentes."},
    "An independent, non-chain spot — character beyond a standardized menu, though we don't yet have enough review text to detail its style.":
        {"es": "Un lugar independiente, sin cadena — carácter más allá de un menú estandarizado, aunque aún no tenemos suficientes reseñas para detallar su estilo.",
         "pt": "Um lugar independente, sem rede — personalidade além de um cardápio padronizado, embora ainda não tenhamos avaliações suficientes para detalhar seu estilo."},
}

# route_tradeoff_note templates (full sentences with a numeric placeholder). Matched/translated as a
# whole BEFORE fragment passes so the {eta}/{delay} number is preserved and no English tail remains.
# Each entry: compiled regex (one number group) -> {es, pt} format strings with {n}.
ROUTE_TEMPLATES = [
    (r"Strongest pick, but match-day traffic adds ~(\d+) min by car right now — leave early or take transit\.",
     {"es": "La mejor opción, pero el tráfico del día del partido suma ~{n} min en auto ahora mismo — sal temprano o usa transporte público.",
      "pt": "A melhor escolha, mas o trânsito do dia do jogo adiciona ~{n} min de carro agora — saia cedo ou use transporte público."}),
    (r"Closest to the stadium \(~(\d+) min\) — easy to reach, though the post-match exit gets congested\.",
     {"es": "Lo más cerca del estadio (~{n} min) — fácil de llegar, aunque la salida tras el partido se congestiona.",
      "pt": "O mais perto do estádio (~{n} min) — fácil de chegar, embora a saída pós-jogo fique congestionada."}),
    (r"Easiest by VTA/Caltrain \(~(\d+) min\) — skips the match-day road gridlock\.",
     {"es": "Lo más fácil en VTA/Caltrain (~{n} min) — evita el atasco vial del día del partido.",
      "pt": "Mais fácil de VTA/Caltrain (~{n} min) — evita o congestionamento do dia do jogo."}),
    (r"Great before the match, but driving out right after is gridlocked \(~(\d+) min extra\) — walk it off or take transit\.",
     {"es": "Genial antes del partido, pero salir en auto justo después es un atasco (~{n} min extra) — camina un poco o usa transporte público.",
      "pt": "Ótimo antes do jogo, mas sair de carro logo depois trava (~{n} min extra) — caminhe um pouco ou use transporte público."}),
    (r"A bit farther out, but outside the stadium traffic pocket — faster and easier to reach and leave \(~(\d+) min\)\.",
     {"es": "Un poco más lejos, pero fuera de la zona de tráfico del estadio — más rápido y fácil para llegar y salir (~{n} min).",
      "pt": "Um pouco mais longe, mas fora da zona de trânsito do estádio — mais rápido e fácil para chegar e sair (~{n} min)."}),
    (r"About (\d+) min each way; plan for match-day delays\.",
     {"es": "Unos {n} min por trayecto; cuenta con demoras el día del partido.",
      "pt": "Cerca de {n} min por trajeto; conte com atrasos no dia do jogo."}),
]
# route notes with NO number (whole-string)
ROUTE_FIXED = {
    "A short detour off the main route — worth it if you have the time.":
        {"es": "Un pequeño desvío de la ruta principal — vale la pena si tienes tiempo.",
         "pt": "Um pequeno desvio da rota principal — vale a pena se você tiver tempo."},
    "Keep as a backup if traffic or crowds get bad — easier to reach and leave.":
        {"es": "Tenlo como alternativa si el tráfico o la multitud empeoran — más fácil para llegar y salir.",
         "pt": "Deixe como alternativa se o trânsito ou a multidão piorarem — mais fácil para chegar e sair."},
}
# fragment -> {es, pt}  (applied as substring replacements; order matters, longest first)
FRAG = {
    "info unverified — call ahead": {"es": "info no verificada — llama antes", "pt": "info não verificada — ligue antes"},
    "verify directly before relying on it": {"es": "verifica directamente antes de confiar", "pt": "confirme diretamente antes de confiar"},
    "not verified — confirm with the business": {"es": "no verificado — confirma con el negocio", "pt": "não verificado — confirme com o local"},
    # halal/kosher name-signal note (from food_safety._religious_signal) — was English in es/pt cards
    "per its name/listing — confirm kitchen/zabiha with the venue": {"es": "(según su nombre/ficha) — confirma la cocina/zabiha con el local", "pt": "(pelo nome/listagem) — confirme a cozinha/zabiha com o local"},
    "per its name/listing — confirm kitchen/kosher with the venue": {"es": "(según su nombre/ficha) — confirma la cocina/kosher con el local", "pt": "(pelo nome/listagem) — confirme a cozinha/kosher com o local"},
    "not verified — check menu": {"es": "no verificado — revisa el menú", "pt": "não verificado — confira o cardápio"},
    "verified-safe options": {"es": "opciones verificadas como seguras", "pt": "opções verificadas como seguras"},
    "offers ": {"es": "ofrece ", "pt": "oferece "},
    " (allergy)": {"es": " (alergia)", "pt": " (alergia)"},
    "easy from VTA/Caltrain": {"es": "fácil desde VTA/Caltrain", "pt": "fácil de VTA/Caltrain"},
}
ALLERGEN = {
    "milk": {"es": "leche", "pt": "leite"}, "eggs": {"es": "huevos", "pt": "ovos"},
    "fish": {"es": "pescado", "pt": "peixe"}, "shellfish": {"es": "mariscos", "pt": "frutos do mar"},
    "tree nuts": {"es": "nueces", "pt": "nozes"}, "peanuts": {"es": "maní", "pt": "amendoim"},
    "wheat gluten": {"es": "gluten", "pt": "glúten"}, "soy": {"es": "soja", "pt": "soja"},
    "sesame": {"es": "ajonjolí", "pt": "gergelim"}, "halal": {"es": "halal", "pt": "halal"},
    "kosher": {"es": "kosher", "pt": "kosher"}, "no_pork": {"es": "sin cerdo", "pt": "sem porco"},
    "vegan": {"es": "vegano", "pt": "vegano"}, "vegetarian": {"es": "vegetariano", "pt": "vegetariano"},
}


def localize(text: str, lang: str) -> str:
    if not text or lang not in ("es", "pt"):
        return text
    if text in FIXED:
        return FIXED[text][lang]
    if text in DEPTH:
        return DEPTH[text][lang]
    if text in ROUTE_FIXED:
        return ROUTE_FIXED[text][lang]
    # full route-note templates (preserve the {eta}/{delay} number, translate the whole sentence)
    for rx, tr in ROUTE_TEMPLATES:
        m = re.fullmatch(rx, text)
        if m:
            return tr[lang].format(n=m.group(1))
    out = text
    # DEPTH fragments (praise / character labels / prefixes), longest-first so a composed narrative
    # like "What a national chain can't replicate here: X; Y." is fully translated piece by piece.
    for frag, tr in sorted(DEPTH.items(), key=lambda kv: -len(kv[0])):
        if frag in out:
            out = out.replace(frag, tr[lang])
    # "<Cuisine> cooking" -> "cocina <Cuisine>" / "culinária <Cuisine>" (the cuisine-cooking component
    # of local_character). Run AFTER DEPTH so fixed labels ("...traditional cooking") aren't mangled.
    # cuisine label may carry a parenthetical sub-type, e.g. "Mexican (taqueria) cooking"
    out = re.sub(r"\b([A-Z][A-Za-z]+(?:\s*\([^)]*\))?) cooking\b",
                 lambda m: (f"cocina {m.group(1)}" if lang == "es" else f"culinária {m.group(1)}"), out)
    # templates
    out = re.sub(r"(\d(?:\.\d)?)★ from (\d+)\+ reviews",
                 lambda m: (f"{m.group(1)}★ de {m.group(2)}+ reseñas" if lang == "es"
                            else f"{m.group(1)}★ de {m.group(2)}+ avaliações"), out)
    out = re.sub(r"~([\d.?]+)km from the stadium",
                 lambda m: (f"a ~{m.group(1)}km del estadio" if lang == "es" else f"a ~{m.group(1)}km do estádio"), out)
    out = re.sub(r"~([\d.?]+)km from Levi's",
                 lambda m: (f"a ~{m.group(1)}km de Levi's" if lang == "es" else f"a ~{m.group(1)}km do Levi's"), out)
    _ln = {"es": {"Spanish": "español", "Portuguese": "portugués", "Italian": "italiano",
                  "Vietnamese": "vietnamita", "Arabic": "árabe", "French": "francés"},
           "pt": {"Spanish": "espanhol", "Portuguese": "português", "Italian": "italiano",
                  "Vietnamese": "vietnamita", "Arabic": "árabe", "French": "francês"}}.get(lang, {})

    def _menu(m):
        names = "/".join(_ln.get(x, x) for x in m.group(1).split("/"))
        return (f"menú y servicio en {names}" if lang == "es" else f"cardápio e serviço em {names}")
    out = re.sub(r"([A-Za-z]+(?:/[A-Za-z]+)*) menu & service", _menu, out)
    # fragments (longest first) + allergen names
    for frag, tr in sorted(FRAG.items(), key=lambda kv: -len(kv[0])):
        if frag in out:
            out = out.replace(frag, tr[lang])
    for en, tr in ALLERGEN.items():
        out = re.sub(rf"\b{re.escape(en)}\b", tr[lang], out)
    return out


def localize_list(items, lang):
    return [localize(x, lang) for x in (items or [])]
