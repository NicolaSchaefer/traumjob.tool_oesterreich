import os
import re
import json
from typing import List

from dotenv import load_dotenv
import anthropic
from data import get_berufsfeld_by_id

load_dotenv(override=True)

def _get_client():
    api_key = os.getenv("ANTHROPIC_API_KEY") or ""
    if api_key:
        return anthropic.Anthropic(api_key=api_key)
    return anthropic.Anthropic()  # liest ANTHROPIC_API_KEY automatisch aus der Umgebung

MODEL = "claude-sonnet-4-6"


def _call(system: str, user: str, max_tokens: int = 2000) -> str:
    msg = _get_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = msg.content[0].text
    # Wenn Antwort abgeschnitten wurde, bis zum letzten vollständigen Objekt kürzen
    if msg.stop_reason == "max_tokens":
        last = max(text.rfind("}"), text.rfind("]"))
        if last != -1:
            text = text[:last+1]
    return text


def _parse_json(raw: str):
    """Robustes JSON-Parsing – toleriert Markdown-Blöcke und abgeschnittene Antworten."""
    raw = raw.strip()
    # Markdown-Codeblock entfernen
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    # Erstes { oder [ bis zum letzten } oder ] extrahieren
    for start, end in [('{', '}'), ('[', ']')]:
        s = raw.find(start)
        e = raw.rfind(end)
        if s != -1 and e != -1 and e > s:
            candidate = raw[s:e+1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # Versuch: bei abgeschnittenem Array das letzte unvollständige Objekt entfernen
                # Suche nach dem letzten vollständigen Objekt-Ende vor dem Fehler
                fixed = _try_repair_truncated(candidate)
                if fixed is not None:
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        pass
    return json.loads(raw)


def _try_repair_truncated(s: str):
    """Versucht eine abgeschnittene JSON-Antwort zu reparieren.

    Entfernt das letzte unvollständige Objekt aus einem Array und schließt
    offene Klammern/Brackets sauber.
    """
    # Letzte Position eines vollständigen Objektes "}," oder "}]"
    # innerhalb des Strings finden
    depth = 0
    in_string = False
    escape = False
    last_safe = -1
    for i, c in enumerate(s):
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 1:
                # Ein vollständiges Element innerhalb des äußeren Objekts/Arrays
                last_safe = i
    if last_safe < 0:
        return None
    head = s[: last_safe + 1]
    # Offene Klammern zählen und schließen
    opens = []
    in_string = False
    escape = False
    for c in head:
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c in "{[":
            opens.append(c)
        elif c in "}]":
            if opens:
                opens.pop()
    closer = {"{": "}", "[": "]"}
    head += "".join(closer[c] for c in reversed(opens))
    return head


SYSTEM_BASE = """Du schreibst für mentortain.me, das Mentoring-Tool von Nicola Schaefer. Es richtet sich an Menschen, die beruflich neu denken wollen: Jugendliche und junge Erwachsene vor der ersten Berufswahl genauso wie Berufstätige, die in ihrem aktuellen Job unzufrieden sind oder noch einmal komplett neu anfangen möchten – egal in welchem Alter.

Schreib so, wie ein vertrauter Mensch tatsächlich spricht. Nicht wie eine KI. Nicht wie ein Coach. Nicht wie ein Ratgebertext.

ABSOLUTE TONREGELN (immer einhalten):
1. Sprich die Person IMMER direkt mit "du" an. Niemals in der dritten Person ("die Person", "sie ist", "ihr Profil"). Auch nicht in einer Aufzählung. Statt "ist ehrlich" schreib "du bist ehrlich". Statt "kann gut zuhören" schreib "du kannst gut zuhören".
2. Keine Gedankenstriche mitten im Satz als Stilmittel. Also kein "xyz – und das ist...". Lieber zwei Sätze.
3. Keine Bindestriche in zusammengesetzten Wörtern. "Berufsfeld" statt "Berufs-Feld", "KI Auswertung" statt "KI-Auswertung".
4. Keine Spiegelformeln wie "das ist klug, nicht langsam" oder "ist eine Stärke, keine Schwäche". Klingt sofort nach KI.
5. Kein Coaching-Wortschatz: kein "tragend", "Mindset", "Potenzial entfalten", "in deiner Mitte", "Energie", "Manifestation".
6. Keine pathetischen Halbsätze wie "Neue Umgebungen, neue Menschen. Das formt." Lieber konkret werden.
7. Keine generischen Beruhigungen wie "es muss sich nicht sofort 100% richtig anfühlen". Lieber konkret raten.
8. KEINE deutenden KI-Sätze wie "und das ist kein Zufall", "das hat einen Grund", "das muss kein Rückfall sein", "das zeigt etwas über dich". Solche Bedeutungsdeutungen klingen sofort nach KI. Stattdessen einfach konkret werden, was die Person tun kann.
9. KEINE überhöhenden Formulierungen wie "Du hast als Kind von Mode geträumt" – stattdessen normal: "Mode hat dich schon als Kind interessiert" oder einfach "Mode war für dich schon immer ein Thema".
10. Sätze, die mit "Das" oder "Es" anfangen und etwas deuten, sind verdächtig. Wenn du sie schreibst, lösch sie wieder.
11. KEINE selbstbeweihräuchernden Beruhigungen wie "Du bist ehrlich, auch mit dir selbst. Das ist seltener als du denkst." Niemand redet so. Lass es weg.
12. KEINE Tröstungs-Schleifen wie "Du musst dich für nichts entscheiden, nur ehrlich hinspüren." Klingt nach Coach im Werbevideo.
13. KEINE deutenden Gedankengänge wie "Der Druck kommt nicht daher dass du falsch liegst, sondern daher dass...". Das ist ChatGPT-Deutung pur. Wenn du Druck ansprechen willst, dann konkret und kurz.

WIE STATTDESSEN:
- Kurze, direkte Sätze. So wie man spricht.
- Beziehe dich konkret auf das, was die Person geschrieben hat.
- Mut machen heißt konkret: ruf an, frag deine Eltern, mach einen Schnuppertag, geh hin.
- Wenn du Eigenschaften ansprichst, dann immer: "du kannst gut zuhören", "dir liegt das", "du bist eher ruhig" – nie "ist", "kann", "hat".

TECHNIK:
- Immer auf Deutsch
- "du/dir/dich/dein" immer klein (außer Satzanfang)
- IMMER korrekte Umlaute: ä, ö, ü, Ä, Ö, Ü, ß. Niemals ae, oe, ue.
- Keine absoluten Aussagen, keine Diagnosen
- Keine Wörter wie "immer", "nie", "alle", "keiner" wenn vermeidbar"""


def _lebenszahl(geburtsdatum: str) -> int:
    """Berechnet die numerologische Lebenszahl aus einem Geburtsdatum (TT.MM.JJJJ oder JJJJ-MM-TT)."""
    digits = [c for c in geburtsdatum if c.isdigit()]
    if not digits:
        return 0
    s = sum(int(d) for d in digits)
    while s > 9 and s not in (11, 22, 33):
        s = sum(int(c) for c in str(s))
    return s


def _build_extra_perspektiven(fakten: dict) -> str:
    """Baut den optionalen Zusatzabschnitt für Numerologie, Astrologie, Human Design.

    Liefert auch dann etwas Sinnvolles, wenn nur das Interesse angeklickt wurde
    und keine vollständigen Geburtsdaten vorliegen.
    """
    teile = []

    interesse_hd = fakten.get("interesse_human_design", "nein")
    interesse_num = fakten.get("interesse_numerologie", "nein")
    interesse_astro = fakten.get("interesse_astrologie", "nein")
    geburtsdatum = fakten.get("geburtsdatum", "")
    geburtsort = fakten.get("geburtsort", "")
    geburtsuhrzeit = fakten.get("geburtsuhrzeit", "")
    sternzeichen = fakten.get("sternzeichen", "")

    hat_interesse = any(v in ("ja", "vielleicht") for v in [interesse_hd, interesse_num, interesse_astro])
    if not hat_interesse:
        # Wenn die Person bei allen drei "nein" angeklickt hat, NICHTS hinzufügen.
        return ""

    teile.append(
        "\nDie Person hat Interesse an folgenden Perspektiven angeklickt. "
        "WICHTIG: Erfinde NICHTS dazu. Wenn keine Geburtsdaten vorliegen, gib KEINEN persönlichen Befund, "
        "sondern nur allgemeine Gedankenanstöße. Beginne den ersten Eintrag mit einem ehrlichen Rahmungssatz "
        "wie: 'Viele Menschen finden diese Perspektiven spannend für die Berufswahl. Hier ein paar Gedankenanstöße – "
        "kein Urteil, keine Diagnose.'"
    )

    # Astrologie
    if interesse_astro in ("ja", "vielleicht"):
        if sternzeichen:
            teile.append(f"- ASTROLOGIE: Sternzeichen ist {sternzeichen}. Beschreibe sanft die typischen Stärken dieses Zeichens als Anregung. Mach klar, dass das nur ein erster Anhaltspunkt ist und ein echter astrologischer Blick mit Geburtsstunde und -ort viel mehr zeigt.")
        else:
            teile.append("- ASTROLOGIE: Kein Sternzeichen angegeben. Erkläre nur allgemein, was eine astrologische Sicht auf den Beruf einbringen kann (Stärken, Energiequalität, Lebensthemen) und wo man ein kostenloses Geburtshoroskop erstellen lassen kann (z.B. astro.com). KEINE konkreten Aussagen über die Person.")

    # Numerologie – Lebenszahl wird in Python berechnet, damit nichts halluziniert wird
    if interesse_num in ("ja", "vielleicht"):
        if geburtsdatum:
            lz = _lebenszahl(geburtsdatum)
            teile.append(f"- NUMEROLOGIE: Aus dem Geburtsdatum {geburtsdatum} wurde die Lebenszahl {lz} berechnet (Quersumme). Beschreibe in 2-3 Sätzen, was diese Lebenszahl klassisch numerologisch bedeutet und welche beruflichen Themen typischerweise dazu passen. Mach klar: das ist ein Gedankenanstoß, kein Urteil.")
        else:
            teile.append("- NUMEROLOGIE: Kein Geburtsdatum angegeben. Erkläre nur kurz und allgemein, was die Lebenszahl ist (Quersumme aus dem Geburtsdatum, ergibt eine Zahl von 1 bis 9 plus Meisterzahlen 11/22/33), und dass jede Zahl typische Themen mitbringt. KEINE konkrete Aussage über die Person.")

    # Human Design
    if interesse_hd in ("ja", "vielleicht"):
        teile.append(
            "- HUMAN DESIGN: Erkläre kurz, dass es 5 Energietypen gibt (Generator, Manifestierender Generator, Manifestor, Projektor, Reflektor) und dass jeder eine andere natürliche Strategie hat, sich zu bewegen und Entscheidungen zu treffen. "
            "WICHTIG: Rate NIEMALS einen HD-Typ aus dem Geburtsdatum. Eine echte Berechnung braucht Geburtsdatum, -ort UND genaue Uhrzeit. "
            "Empfehle stattdessen, ein kostenloses Chart bei mybodygraph.com oder jovianarchive.com zu erstellen. "
            "Gib einen allgemeinen Gedankenanstoß, warum HD für die Berufswahl spannend sein kann (Manifestor initiiert, Generator reagiert auf das was zu ihm kommt, Projektor wird eingeladen, Reflektor spiegelt das Umfeld). "
            "Kein konkretes Urteil über die Person."
        )

    if len(teile) < 2:
        return ""

    teile.append("Kennzeichne diese Abschnitte im JSON unter dem Schlüssel 'extra_perspektiven' als Liste kurzer Texte (jeweils 2-3 Sätze, mit du formuliert). Bleib bei dem, was wirklich aus den Daten ableitbar ist.")
    return "\n".join(teile)


def _ist_antwort_fluendig(process_data: dict) -> bool:
    """Gibt True zurück, wenn die Antworten inhaltlich sehr dünn sind."""
    reflexion = process_data.get("reflexion") or {}
    vergleich = process_data.get("vergleich") or {}

    # Alle Freitextfelder zusammensammeln
    freitexte = [
        reflexion.get("selbst_eigene_sicht", ""),
        reflexion.get("hobbys", ""),
        reflexion.get("antreiber", ""),
        reflexion.get("stundenlang", ""),
        reflexion.get("was_macht_gluecklich", ""),
        reflexion.get("werte", ""),
        reflexion.get("millionen_frage", ""),
        reflexion.get("kindheitstraum", ""),
        reflexion.get("jetzt_entscheidung", ""),
        reflexion.get("innere_gedanken", ""),
    ]
    gesamt_text = " ".join(t for t in freitexte if t)

    # Fast ausschließlich "kein Bock"
    bock = len(vergleich.get("bock", []))
    kein_bock = len(vergleich.get("kein_bock", []))
    nur_kein_bock = kein_bock > 20 and bock < 5

    # Sehr wenig Text insgesamt
    sehr_wenig_text = len(gesamt_text.strip()) < 150

    return nur_kein_bock or sehr_wenig_text


def generate_auswertung(process_data: dict) -> dict:
    """Hauptauswertung: beruflicher Fingerabdruck + Top 15 Berufe + Motivationsmuster."""

    fakten = process_data.get("fakten") or {}
    extra = _build_extra_perspektiven(fakten)
    hat_extra = bool(extra)
    duenne_antworten = _ist_antwort_fluendig(process_data)

    extra_json = ""
    if hat_extra:
        extra_json = ',\n  "extra_perspektiven": ["Hinweis 1 zu Astrologie/Numerologie/Human Design", "Hinweis 2"]'

    ehrlichkeit_hinweis = ""
    if duenne_antworten:
        ehrlichkeit_hinweis = """
WICHTIG: Die Antworten dieser Person sind sehr knapp oder sie hat kaum etwas mit 'Bock' markiert.
Im 'goldener_tropfen'-Feld: Schreib der Person ehrlich und freundlich, dass du auf dieser Basis nur eine grobe Richtung geben kannst, weil du fast nichts über sie weißt. Lade sie ein, nochmal durchzugehen und ehrlich zu antworten – das macht die Auswertung viel wertvoller.
Wichtig: Verwechsle "weiß" und "fehlt" nicht. Korrekte Formulierung: "weil ich fast nichts über dich weiß" (NICHT "weil mir fast nichts über dich fehlt").
Sprich die Person direkt mit "du" an. Keine Kritik, sondern echte Einladung.
Schlage trotzdem 15 Berufe vor, aber sag dazu, dass diese auf sehr wenigen Informationen basieren.
"""

    # Namen der außergewöhnlichen Berufe für die Empfehlung
    from data import AUSSERGEWOEHNLICHE_BERUFE as _ABL
    aussergewoehnliche_namen = [b["name"] for b in _ABL]

    user_prompt = f"""Hier sind alle Antworten einer Person, die herausfinden möchte, welcher Berufsweg zu ihr passt:

{json.dumps(process_data, ensure_ascii=False, indent=2)}
{extra}
{ehrlichkeit_hinweis}

Bitte erstelle eine strukturierte Auswertung als JSON mit genau diesem Format:
{{
  "goldener_tropfen": "2-4 Sätze, die die Essenz dieser Person beschreiben.",
  "motivationsmuster": ["Du brauchst Sinn in deiner Arbeit", "Du arbeitest gern mit Menschen", "..."],
  "staerken": ["Du kannst gut zuhören", "Du erklärst komplexe Dinge einfach", "..."],
  "top_berufe": [
    {{
      "name": "Berufsbezeichnung",
      "bereich": "z.B. Medizin und Gesundheit",
      "warum": "2-3 Sätze, IMMER mit du formuliert. Konkret was an DIESER Person zum Beruf passt.",
      "bedenke_dabei": "2-3 Sätze ehrliche Einordnung, was bei diesem Weg anstrengend, schwierig oder nicht ganz passend sein könnte. Konkret: Was musst du lernen? Was wird hart? Wo gibt es vielleicht Reibung mit deinem Profil? Was sind finanzielle, soziale oder Studien-Realitäten? Keine harte Kritik, klare Einordnung.",
      "woran_du_testen_kannst": "1-2 Sätze, was du konkret tun kannst, um herauszufinden ob das wirklich zu dir passt. Beispiel: 'Sprich mit jemandem, der das macht, oder mach einen Schnuppertag.'",
      "ausbildungsweg": "z.B. Studium, Ausbildung, duales Studium",
      "kreativ_potenzial": "Ein Satz zur kreativen Ausprägung, mit du formuliert."
    }}
  ]{extra_json},
  "aussergewoehnliche_empfehlung": ["Name1", "Name2", "Name3", "Name4"]
}}

WICHTIG: Dieses Tool richtet sich ausschließlich an Schüler:innen in Österreich (AHS, BHS, NMS, Berufsschule). Schlage keine Studiengänge als primären Weg vor, sondern österreichische Ausbildungswege: Lehre, BMS, BHS-Abschluss, und wo passend auch Studium als Ergänzung. Verwende österreichische Begriffe: Matura (nicht Abitur), Lehre (nicht Ausbildung), AMS (nicht Bundesagentur für Arbeit), BIC.at als Berufsinfoqeuelle.

WICHTIGE FORMATIERUNGSREGELN für motivationsmuster, staerken und warum:
- IMMER vollständige Sätze in der DU-Form. NIEMALS abstrakte Substantive wie "Sinnhaftigkeit vor Gehalt" oder "Kreativität als Grundbedürfnis".
- Schreib statt "Empathie und echtes Zuhören" lieber "Du kannst Menschen wirklich zuhören".
- Schreib statt "Sinnhaftigkeit vor Gehalt" lieber "Du brauchst Sinn, Geld ist dir nicht das Wichtigste".
- Jeder Eintrag in motivationsmuster und staerken beginnt mit "Du" oder "Dir" oder "Dich".

Für "aussergewoehnliche_empfehlung": Wähle genau 4 Einträge aus dieser Liste, die am besten zu dieser Person passen:
{json.dumps(aussergewoehnliche_namen, ensure_ascii=False)}

TON: Bleib warm und menschlich, aber sei AUCH KRITISCH und einordnend. Nicht alles muss positiv klingen. Wenn etwas nicht ganz passt, sag es klar. Lieber ehrlich als nur bestätigend.

UMGANG MIT WUNSCH-OPTIONEN: Wenn die Person in "reflexion.jetzt_entscheidung" oder "reflexion.kindheitstraum" konkrete Berufe nennt, ÜBERNIMM sie nicht einfach in die Top 15. Stattdessen:
- Falls eine genannte Wunschoption sehr gut zum Profil passt: rein in Top 15 mit besonderem Hinweis "Du hast das selbst genannt – und das passt aus folgendem Grund tatsächlich"
- Falls eine genannte Wunschoption NICHT optimal passt: trotzdem in Top 15 aufnehmen, aber im "bedenke_dabei" klar benennen wo die Reibung mit dem Profil liegt
- Im "goldener_tropfen" ein kurzer Satz zu den selbst genannten Wünschen: ob sie sich im Profil bestätigen oder ob da eine Spannung zu sehen ist

Wichtig: Falls die Person bereits berufstätig ist (Feld "fakten.situation" ist "arbeite", "neu_anfangen" oder "pause") und im Feld "fakten.aktueller_beruf" einen Beruf nennt:
- Erwähne im "goldener_tropfen" oder "warum"-Texten ihre bisherige Erfahrung als ECHTE Stärke, nicht als Hindernis.
- Schlage Berufe vor, in denen ihre übertragbaren Kompetenzen (Feld "uebertragbare_staerken") wirklich genutzt werden – nicht nur Anfängerberufe.
- Wenn sie unzufrieden ist (Feld "job_unzufriedenheit"), greife konkret auf, was sie vermisst, und stelle Berufe in den Vordergrund, die genau das bieten.
- Mach klar: Neu anfangen mit 30, 40 oder 50 ist möglich und sinnvoll. Quereinstieg ist eine reale Option, kein Notnagel.
- Berücksichtige bei "ausbildungsweg": Quereinstieg, Weiterbildung, Umschulung (BfA), Studium berufsbegleitend, Selbstständigkeit – nicht nur klassische Erstausbildung.

Wichtig: Im Feld "werte" steht die Werte-Auktion (100 Punkte verteilt). Die Werte mit den höchsten Punkten sind ZENTRAL für die Berufswahl – das ist, was die Person wirklich antreibt. Wenn jemand z.B. 30 Punkte auf "freiheit" und 25 auf "sinn" gegeben hat: Berufe mit Selbstständigkeits-Option und sinnvoller Arbeit weit oben. Werte mit 0 Punkten kannst du de-priorisieren.

Wichtig: Im Feld "energie" steht eine Stunden-zu-Energielevel-Map (z.B. {{"6": 1, "7": 3, ...}}, Skala 0-5). Morgen-Menschen (hohe Werte um 6-10 Uhr) passen gut zu Berufen mit frühem Start. Abend-Menschen (hohe Werte ab 18-22 Uhr) passen besser zu flexiblen oder kreativen Berufen. Erwähne das im "bedenke_dabei" eines passenden Berufs, falls relevant.

Wichtig: Im Feld "charakter" stehen Selbsteinschätzungen auf einer Skala von 0 (gar nicht) bis 5 (voll und ganz).
- Werte 4-5 sind ausgeprägte Stärken: nutze sie als wichtigen Hinweis, welche Berufe passen.
- Werte 0-1 zeigen Bereiche, in denen sich die Person nicht wohlfühlt: vermeide Berufe, die genau diese Eigenschaften zwingend brauchen.
- Werte 2-3 sind neutral: nicht überbewerten, aber im Hinterkopf behalten.
Erwähne im "warum" gerne mal direkt, welcher Charakter-Wert genau zum Beruf passt (z.B. "Du hast hohe Empathie und Geduld, das ist hier zentral").

Wichtige Hinweise für die top_berufe:
- Die Liste soll genau 15 Einträge enthalten.
- Denke über den Tellerrand: Neben klassischen Berufen auch ungewöhnliche Kombinationen einbauen – z.B. KI-Koordinator/in, Startup-Gründung, Unternehmertum studieren, internationale Karriere, Familienunternehmen übernehmen, Social Entrepreneurship, Content Creation als Beruf, digitale Nomaden-Berufe.
- Wenn die Person Auslandserfahrung, Sprachen oder Reiseinteresse zeigt: internationale Wege konkret benennen (welches Land, welcher Kontext).
- Wenn Unternehmertum, Selbstständigkeit oder kreative Freiheit sichtbar ist: mindestens einen Gründungsweg vorschlagen.
- Wenn Technik oder Digitales sichtbar ist: KI-nahe Berufe einbauen (Prompt Engineer, AI-Trainer, Tech-Produktmanager).
- Blinde Flecken aufdecken: Was erwähnt die Person beiläufig, das auf einen Beruf hindeutet, den sie selbst nicht nennt? (Beispiel: trägt Brille → Optiker/in; spielt leidenschaftlich Videospiele → Game Designer, Esports Manager, Spielejournalist; ist ruhig und geduldig → Archivar/in, Bibliothekar/in, Dokumentar/in, Restaurator/in). Solche Berufe gehören unbedingt in die Liste.
- WICHTIG: Mindestens 3 von den 15 Berufen sollen WENIGER BEKANNTE Ausbildungs- oder Studienwege sein, die viele junge Leute nicht auf dem Schirm haben. Denk an: Zerspanungsmechaniker/in, Mediengestalter/in Bild und Ton, Industriemechaniker/in, Fachinformatiker/in (mit Vertiefungen), Veranstaltungstechniker/in, Werkstoffprüfer/in, Tiermedizinische/r Fachangestellte/r, Tischler/in, Fluggerätmechaniker/in, Augenoptiker/in, Hörakustiker/in, Orthopädieschuhmacher/in, Forstwirt/in, Buchbinder/in, Maßschneider/in, Bestatter/in, Vermessungstechniker/in, Geomatiker/in, Mechatroniker/in für Kältetechnik, Brauer/in und Mälzer/in, Steinmetz/in, Glasbläser/in, Fachangestellte/r für Medien- und Informationsdienste, Notfallsanitäter/in, Hebamme, Bestattungsfachkraft, Pferdewirt/in, Winzer/in, Drohnenpilot/in, Restaurator/in im Handwerk, Goldschmied/in, Hörgeräteakustiker/in. Wenn das Profil zu einem dieser Berufe passt: konkret nennen, nicht nur Klassiker.
- MOBILITÄT BERÜCKSICHTIGEN: Im Feld "fakten.mobilitaet" steht, wo die Person bereit wäre zu starten. Wenn "nur_heimat" oder "andere_stadt": realistisch dort denken, kein "nach Hamburg ziehen" als selbstverständlich. Wenn "bundesweit" oder "ausland": ruhig auch Berufe vorschlagen, die nur an wenigen Orten gehen.
- FINANZIERUNG ERWÄHNEN: Im Feld "fakten.finanzierung" steht, was die Person sich finanziell vorstellt. Wenn knapp/unsicher: bei "bedenke_dabei" oder "ausbildungsweg" konkret österreichische Finanzierungsoptionen nennen (Studienbeihilfe, Lehrlingsförderungen des AMS, Lehre mit Gehalt, Bildungsstipendium der WKO, Begabtenförderung für Lehrlinge). Bei Lehrberufen mit Lehrlingsentschädigung: das positiv hervorheben.
- Wenn die Person Musik oder Tanz erwähnt: konkrete Berufe nennen (Musikpädagog/in, Bandmanager, Choreograf/in, Musikproduktion).
- Persönlichkeit als Stärke deuten: Eine ruhige, zurückhaltende Art ist KEIN Mangel, sondern ein Asset – z.B. für Berufe, die Präzision, Geduld oder tiefes Zuhören erfordern. Das so benennen.
- Vier Energie-Quadranten berücksichtigen (aus den Antworten ableiten): Blau (Harmonie, Ordnung, Struktur), Rot (Leadership, Dominanz, Durchsetzung), Grün (Leichtigkeit, Inspiration, Kreativität), Gelb (Beziehung, Wärme, Teamgefühl). Lass diese Muster in die Berufswahl einfließen.
- Wenn Druck, Angst oder Entscheidungslähmung aus den Antworten spricht (Felder 'gedanken_im_kopf' und 'angst_druck'): Nimm das ernst. Geh im 'goldener_tropfen' direkt darauf ein – nicht heilend, aber klar benennend. Wähle Berufe, die zu einem klaren, überschaubaren Start passen, und gib im 'warum' einen kurzen ermutigenden Hinweis.
- Geld ist nicht alles: Wenn ein Ausbildungs- oder Studienweg inhaltlich passt, aber finanziell knapp klingt, darauf hinweisen, dass finanzielle Lücken überbrückbar sind (BAföG, Stipendien, Nebenjob, duales Studium). Einen Beruf wegen Geld zu meiden, den man liebt, ist ein teurer Fehler.
- Halte 'warum' konkret und persönlich – nicht generisch. Beziehe dich auf das, was die Person gesagt hat.
- Bei 'ausbildungsweg' ruhig auch "Gründen", "Selbststudium + Community", "Work & Travel + Zertifikat" nennen, wenn passend.
Gib nur das JSON zurück, ohne weitere Erklärungen."""

    raw = _call(SYSTEM_BASE, user_prompt, max_tokens=8000)
    return _parse_json(raw)


def extract_from_dokument(text: str) -> dict:
    """Liest ein hochgeladenes Dokument und extrahiert alle passenden Formularfelder."""
    user_prompt = f"""Dokument einer Person (Berufsberatung):

---
{text[:4000]}
---

Extrahiere relevante Infos. Nur Felder befüllen, die wirklich im Text stehen. Kurze Werte (max 2 Sätze pro Feld).

{{
  "fakten": {{
    "vorname": "", "alter": "", "bundesland": "", "schulform": "",
    "abschluss": "", "note": "", "leistungskurse": "",
    "ausbildung_ja": "", "ausbildung_beruf": "",
    "studium_ja": "", "studium_fach": ""
  }},
  "reflexion": {{
    "selbst_eigene_sicht": "", "hobbys": "", "kann_gut": "",
    "moechte_koennen": "", "werte": "", "sinn": "", "antreiber": "",
    "stundenlang": "", "kindheitstraum": "", "sprachen": "",
    "instrumente": "", "gedanken_im_kopf": "", "angst_druck": "",
    "millionen_frage": "", "jetzt_entscheidung": "",
    "bewunderung": "", "was_macht_gluecklich": ""
  }}
}}

Nur JSON zurückgeben, keine Erklärungen."""

    raw = _call(SYSTEM_BASE, user_prompt, max_tokens=2500)
    return _parse_json(raw)


def get_kreative_ideen(beruf: str, profil_kurz: str) -> List[str]:
    """Kreative und ungewöhnliche Ausprägungen eines Berufs. Wirft bei Fehler – damit Frontend echten Retry anbieten kann."""

    user_prompt = f"""Der Beruf oder Berufsbereich ist: {beruf}

Kurzes Profil der Person: {profil_kurz}

Nenne genau 5 kreative, ungewöhnliche oder besonders persönliche Wege, wie genau DIESE Person diesen Beruf ausleben kann.
Beziehe dich auf das Profil oben – mach die Vorschläge so persönlich wie möglich.
Sprich die Person IMMER direkt mit "du" an. Jeder Vorschlag beginnt mit "Du".

Format: NUR ein JSON-Array mit genau 5 Strings, jeder 2-3 Sätze lang.
Beispiel: ["Du könntest...", "Du könntest...", "Du könntest...", "Du könntest...", "Du könntest..."]"""

    raw = _call(SYSTEM_BASE, user_prompt, max_tokens=900)
    ideen = _parse_json(raw)
    if not isinstance(ideen, list):
        # Falls Dict mit numerierten Keys
        if isinstance(ideen, dict):
            ideen = list(ideen.values())
        else:
            raise ValueError("Antwort hat kein Array-Format")
    ideen = [str(i).strip() for i in ideen if i and str(i).strip()]
    if len(ideen) < 3:
        raise ValueError("Zu wenig Vorschläge erhalten")
    return ideen[:5]


def get_links_fuer_favoriten(favoriten: List[str], profil_kurz: str) -> dict:
    """Kuratierte Infoblöcke für die 5 Favoriten.

    Die KI schlägt fachspezifische Quellen vor (Berufsverband, Fachgesellschaft,
    spezialisiertes Portal). Daraus bauen wir Google-Suchen mit site:-Filter,
    damit nichts halluziniert wird – die Suche landet immer auf der echten Site.
    """
    import urllib.parse

    favoriten_json = json.dumps(favoriten, ensure_ascii=False)

    user_prompt = f"""Du hilfst beim Traumjobtool von mentortain.me. Diese Person hat folgende 5 Berufs-Favoriten:
{favoriten_json}

Ihr Profil (kurz): {profil_kurz}

Gib für JEDEN Beruf ein JSON-Objekt zurück mit:
- "kurzueberblick": 2-3 Sätze, was du in diesem Beruf konkret machst. IMMER mit "du" ansprechen.
- "fachquellen": Liste von genau 3 Objekten mit den BESTEN deutschen Fachseiten/Verbänden für diesen Beruf, jedes Objekt:
    {{"name": "Sprechender Name (z.B. 'Bundesärztekammer')", "domain": "bundesaerztekammer.de", "warum": "Ein Satz warum genau diese Quelle gut ist"}}
  WICHTIG: Wähle WIRKLICH passende Quellen, nicht immer dieselben Standardseiten. Beispiele:
    - Für Physician Assistant: bundesaerztekammer.de, dgpa-online.de
    - Für Erzieher: kita.de, paedagogik-online.de
    - Für IT-Beruf: heise.de, golem.de, gi.de
    - Für Handwerk: handwerk.de, zdh.de
  Wenn du keine spezialisierte Quelle kennst, nimm bekannte Branchenportale, NICHT die Bundesagentur (die kommt extra).
  Domain bitte ohne https:// und ohne www. – nur die reine Domain.

Antworte NUR mit JSON, kein Markdown:
{{
  "BerufName1": {{"kurzueberblick": "...", "fachquellen": [{{"name":"...","domain":"...","warum":"..."}},{{...}},{{...}}]}},
  "BerufName2": {{...}}
}}"""

    try:
        raw = _call(SYSTEM_BASE, user_prompt, max_tokens=3000)
        claude_data = _parse_json(raw)
    except Exception:
        claude_data = {}

    def _build_such_prompt(beruf_name: str) -> str:
        return (
            "Frage eine KI deiner Wahl:\n\n"
            f"„Ich interessiere mich für {beruf_name} als Beruf in Österreich.\n\n"
            "Du bist ein Karriere-Coach mit aktuellem Fachwissen über Lehrberufe, Ausbildungen und "
            "Schulen in Österreich (BHS, BMS, Lehre, FH). Du nutzt echte Webrecherche (Browsing/Agentenmodus "
            "ist aktiviert), um ausschließlich faktenbasierte und aktuelle Informationen zu liefern. "
            "Erfinde nichts dazu!\n\n"
            "🔍 Deine Aufgabe:\n"
            "Recherchiere den gewünschten Beruf oder Studiengang in Echtzeit im Internet. "
            "Gliedere die Infos klar und motivierend, für junge Erwachsene ohne Vorkenntnisse. "
            "Achte auf regionale Unterschiede (z.B. Zugang oder Gehalt). Verwende ausschließlich verlässliche Quellen.\n\n"
            "🔒 Quellen:\n"
            "Nutze alle Quellen, die du finden und als relevant ansehen kannst. ausbildung.de gerne dabei, "
            "aber nicht exklusiv, sondern als eine Quelle von mehreren.\n\n"
            "📄 Strukturierte Ausgabe (PDF-ready):\n"
            "1. 🧾 Berufsbild / Studiengang: Tätigkeiten, Alltag, Einsatzorte, Branchen\n"
            "2. 🎓 Zugang & Voraussetzungen: Schulabschluss, persönliche Eigenschaften, formale Anforderungen\n"
            "3. 📚 Ablauf & Inhalte: Dauer, Aufbau, Fächer/Module, Praxis vs. Theorie\n"
            "4. 💼 Karriere & Gehalt: Aufstieg, Weiterbildung, Gehaltsspannen (regional)\n"
            "5. ⚠️ Realitätscheck: Was ist herausfordernd? Was sollte man vorher wissen?\n\n"
            "🖨️ Formatierung: Klare Gliederung, Absätze, Icons/Emojis. Freundlich, motivierend, ehrlich."
            "“"
        )

    ergebnis = {}
    for beruf in favoriten:
        d = claude_data.get(beruf) or {}
        q = urllib.parse.quote_plus
        fachquellen = d.get("fachquellen") or []

        # Fachquellen: direkt zur Domain, mit Such-Hinweis in Beschreibung
        lies_links = []
        for fq in fachquellen[:3]:
            if not isinstance(fq, dict):
                continue
            name = str(fq.get("name", "")).strip()
            domain = str(fq.get("domain", "")).strip()
            for prefix in ("https://", "http://", "www."):
                if domain.lower().startswith(prefix):
                    domain = domain[len(prefix):]
            warum = str(fq.get("warum", "")).strip()
            if not name or not domain:
                continue
            lies_links.append({
                "titel": name,
                "url": f"https://{domain}",
                "beschreibung": warum + f" Suche dort nach „{beruf}“.",
            })

        ergebnis[beruf] = {
            "kurzueberblick": d.get("kurzueberblick", ""),
            "such_prompt": _build_such_prompt(beruf),
            "schau_dir_an": [
                {
                    "titel": f"YouTube-Videos zu „{beruf}“",
                    "url": f"https://www.youtube.com/results?search_query={q(beruf)}",
                    "beschreibung": "Suche bei YouTube und schau dir an, was du am spannendsten findest.",
                },
            ],
            "lies_dich_ein": lies_links,
            "anker_link": {
                "titel": "BIC – Berufs-Informations-Computer (AMS Österreich)",
                "url": f"https://www.bic.at/index.php?page=searchResults&q={q(beruf)}",
                "beschreibung": "Offizielle österreichische Berufsbeschreibung mit Aufgaben, Verdienst und Ausbildungswegen",
            },
            "sprich_mit_jemandem": [
                f"Frag in deinem Umfeld (Eltern, Verwandte, Bekannte deiner Eltern, Lehrkräfte): Kennt ihr jemanden, der als {beruf} arbeitet oder Erfahrung in dem Bereich hat? Du wirst überrascht sein, wie oft das klappt.",
                f"Schreib jemanden direkt an, der diesen Beruf macht – auf LinkedIn, Instagram oder über das Kontaktformular einer Praxis, Kanzlei oder Firma. Sei bei deiner Nachricht ganz ehrlich. Du kannst z.B. schreiben: „Ich überlege selbst, {beruf} zu werden. Hättest du 15 Minuten Zeit für ein paar Fragen?“ Die meisten sagen ja.",
                "Frag nach einem Schnuppertag oder einem kurzen Praktikum (ein Tag bis eine Woche). Bei Schulen, Praxen, Kanzleien, Werkstätten und Betrieben geht das fast immer, wenn du höflich fragst. Nichts ersetzt das Gefühl, mal vor Ort gewesen zu sein.",
            ],
        }

    return ergebnis
