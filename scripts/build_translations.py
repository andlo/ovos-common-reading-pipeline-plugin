#!/usr/bin/env python3
"""Build locale/<lang>/ for ovos-skill-common-tales for all 7 non-English
languages ovos-skill-fairytales already supports, reusing its translated
dialog text where the slot structure matches unchanged, and adapting/
translating the rest (new dialogs this skill introduces, and the ones
whose slots changed - {story} -> {description}, hardcoded site names ->
{source})."""
import json
import shutil
from pathlib import Path

FAIRYTALES = Path("/home/andlo/ovos-skill-fairytales/locale")
COMMON = Path("/home/andlo/ovos-skill-common-tales/locale")

LANGS = ["da-dk", "de-de", "es-es", "fr-fr", "it-it", "nl-nl", "pt-pt"]

# Files that are byte-for-byte reusable: same slots, same meaning.
REUSE_VERBATIM = [
    "is_it_that.dialog",
    "that_would_be.dialog",
    "no_story.dialog",
    "no_story_to_continue.dialog",
    "continue.dialog",
    "stop_telling_tales.dialog",
    "story_unavailable.dialog",
    "Tales.intent",
    "continue.intent",
]

print("Copying verbatim-reusable files...")
for lang in LANGS:
    src_dir = FAIRYTALES / lang
    dst_dir = COMMON / lang
    dst_dir.mkdir(parents=True, exist_ok=True)
    for fname in REUSE_VERBATIM:
        shutil.copyfile(src_dir / fname, dst_dir / fname)
print("Done with verbatim copies.")

I_KNOW_THAT = {
    "da-dk": "{description}. Lad os begynde...\nJa, {description}. Den lyder sådan her...\n",
    "de-de": "{description}. Fangen wir an...\nJa, {description}. Sie geht so...\n",
    "es-es": "{description}. Empecemos...\nSí, {description}. Empieza así...\n",
    "fr-fr": "{description}. Commençons...\nOui, {description}. Ça commence comme ça...\n",
    "it-it": "{description}. Cominciamo...\nSì, {description}. Inizia così...\n",
    "nl-nl": "{description}. Laten we beginnen...\nJa, {description}. Het gaat zo...\n",
    "pt-pt": "{description}. Vamos começar...\nSim, {description}. Começa assim...\n",
}

FROM_TALES = {
    "da-dk": "Denne historie blev læst op for dig fra {source}.\n",
    "de-de": "Diese Geschichte wurde dir aus {source} vorgelesen.\n",
    "es-es": "Este cuento te lo he leído de {source}.\n",
    "fr-fr": "Cette histoire t'a été lue depuis {source}.\n",
    "it-it": "Questa storia ti è stata letta da {source}.\n",
    "nl-nl": "Dit verhaal werd aan je voorgelezen van {source}.\n",
    "pt-pt": "Esta história foi-lhe lida a partir de {source}.\n",
}

NO_STORY_PROVIDERS = {
    "da-dk": "Jeg har ingen historiefortællere installeret lige nu, så jeg kan ikke fortælle dig nogen historier.\n",
    "de-de": "Ich habe gerade keine Geschichtenerzähler installiert, also kann ich dir keine Geschichten erzählen.\n",
    "es-es": "Ahora mismo no tengo ningún narrador instalado, así que no puedo contarte ningún cuento.\n",
    "fr-fr": "Je n'ai actuellement aucun conteur installé, donc je ne peux pas te raconter d'histoire.\n",
    "it-it": "Al momento non ho nessun narratore installato, quindi non posso raccontarti storie.\n",
    "nl-nl": "Ik heb op dit moment geen verhalenvertellers geïnstalleerd, dus ik kan je geen verhalen vertellen.\n",
    "pt-pt": "Não tenho nenhum contador de histórias instalado agora, por isso não te posso contar nenhuma história.\n",
}

NO_SUCH_COLLECTION = {
    "da-dk": "Jeg kender ikke en historiefortæller ved navn {collection}.\nJeg har ingen historier fra {collection}.\n",
    "de-de": "Ich kenne keinen Geschichtenerzähler namens {collection}.\nIch habe keine Geschichten von {collection}.\n",
    "es-es": "No conozco a ningún narrador llamado {collection}.\nNo tengo ningún cuento de {collection}.\n",
    "fr-fr": "Je ne connais pas de conteur appelé {collection}.\nJe n'ai aucune histoire de {collection}.\n",
    "it-it": "Non conosco nessun narratore chiamato {collection}.\nNon ho nessuna storia di {collection}.\n",
    "nl-nl": "Ik ken geen verhalenverteller die {collection} heet.\nIk heb geen verhalen van {collection}.\n",
    "pt-pt": "Não conheço nenhum contador de histórias chamado {collection}.\nNão tenho nenhuma história de {collection}.\n",
}

TALES_BY_COLLECTION = {
    "da-dk": "(Fortæl|Læs) (mig| ) en historie fra {collection}\n"
             "(Fortæl|Læs) (mig| ) historien {tale} fra {collection}\n"
             "(Fortæl|Læs) (mig| ) en historie af {collection}\n"
             "Find {tale} af {collection}\n"
             "Find {tale} fra {collection}\n"
             "(Fortæl|Læs) (mig| ) en {collection}-historie\n"
             "(Fortæl|Læs) (mig| ) en {collection}-historie om {tale}\n",
    "de-de": "(Erzähl|Lies) (mir| ) eine Geschichte von {collection}\n"
             "(Erzähl|Lies) (mir| ) die Geschichte {tale} von {collection}\n"
             "(Erzähl|Lies) (mir| ) eine Geschichte von {collection}\n"
             "Finde {tale} von {collection}\n"
             "Finde {tale} von {collection}\n"
             "(Erzähl|Lies) (mir| ) eine {collection}-Geschichte\n"
             "(Erzähl|Lies) (mir| ) eine {collection}-Geschichte über {tale}\n",
    "es-es": "(Cuéntame|Léeme) una historia de {collection}\n"
             "(Cuéntame|Léeme) la historia {tale} de {collection}\n"
             "(Cuéntame|Léeme) un cuento de {collection}\n"
             "Busca {tale} de {collection}\n"
             "Busca {tale} de {collection}\n"
             "(Cuéntame|Léeme) un cuento de {collection}\n"
             "(Cuéntame|Léeme) un cuento de {collection} sobre {tale}\n",
    "fr-fr": "(Raconte|Lis)-moi une histoire de {collection}\n"
             "(Raconte|Lis)-moi l'histoire {tale} de {collection}\n"
             "(Raconte|Lis)-moi une histoire de {collection}\n"
             "Trouve {tale} de {collection}\n"
             "Trouve {tale} de {collection}\n"
             "(Raconte|Lis)-moi une histoire de {collection}\n"
             "(Raconte|Lis)-moi une histoire de {collection} sur {tale}\n",
    "it-it": "(Raccontami|Leggimi) una storia di {collection}\n"
             "(Raccontami|Leggimi) la storia {tale} di {collection}\n"
             "(Raccontami|Leggimi) una storia di {collection}\n"
             "Trova {tale} di {collection}\n"
             "Trova {tale} di {collection}\n"
             "(Raccontami|Leggimi) una storia di {collection}\n"
             "(Raccontami|Leggimi) una storia di {collection} su {tale}\n",
    "nl-nl": "(Vertel|Lees) (mij| ) een verhaal van {collection}\n"
             "(Vertel|Lees) (mij| ) het verhaal {tale} van {collection}\n"
             "(Vertel|Lees) (mij| ) een verhaal van {collection}\n"
             "Zoek {tale} van {collection}\n"
             "Zoek {tale} van {collection}\n"
             "(Vertel|Lees) (mij| ) een {collection}-verhaal\n"
             "(Vertel|Lees) (mij| ) een {collection}-verhaal over {tale}\n",
    "pt-pt": "(Conta|Lê)-me uma história de {collection}\n"
             "(Conta|Lê)-me a história {tale} de {collection}\n"
             "(Conta|Lê)-me uma história de {collection}\n"
             "Encontra {tale} de {collection}\n"
             "Encontra {tale} de {collection}\n"
             "(Conta|Lê)-me uma história de {collection}\n"
             "(Conta|Lê)-me uma história de {collection} sobre {tale}\n",
}

SKILL_JSON = {
    "da-dk": {"name": "Historiefortæller",
              "description": "Formidler 'fortæl mig en historie' på tværs af historiefortæller-skills (Andersen, Grimm, Andrew Lang og flere).",
              "examples": ["fortæl historien om Askepot", "læs et eventyr", "fortsæt historien"],
              "tags": ["underholdning", "historier", "eventyr", "orchestrator"]},
    "de-de": {"name": "Geschichtenerzähler",
              "description": "Vermittelt 'erzähl mir eine Geschichte' über mehrere Geschichtenerzähler-Skills (Andersen, Grimm, Andrew Lang und weitere).",
              "examples": ["erzähl mir das Märchen Aschenputtel", "lies mir eine Geschichte vor", "erzähl weiter"],
              "tags": ["unterhaltung", "geschichten", "maerchen", "orchestrator"]},
    "es-es": {"name": "Narrador de Cuentos",
              "description": "Coordina 'cuéntame un cuento' entre varias skills narradoras (Andersen, Grimm, Andrew Lang y más).",
              "examples": ["cuéntame el cuento de Cenicienta", "léeme un cuento", "continúa el cuento"],
              "tags": ["entretenimiento", "cuentos", "orchestrator"]},
    "fr-fr": {"name": "Conteur d'Histoires",
              "description": "Coordonne « raconte-moi une histoire » entre plusieurs skills conteuses (Andersen, Grimm, Andrew Lang et d'autres).",
              "examples": ["raconte-moi l'histoire de Cendrillon", "lis-moi une histoire", "continue l'histoire"],
              "tags": ["divertissement", "histoires", "orchestrator"]},
    "it-it": {"name": "Narratore di Storie",
              "description": "Coordina 'raccontami una storia' tra più skill narratrici (Andersen, Grimm, Andrew Lang e altre).",
              "examples": ["raccontami la storia di Cenerentola", "leggimi una storia", "continua la storia"],
              "tags": ["intrattenimento", "storie", "orchestrator"]},
    "nl-nl": {"name": "Verhalenverteller",
              "description": "Coördineert 'vertel me een verhaal' tussen meerdere verhalenverteller-skills (Andersen, Grimm, Andrew Lang en meer).",
              "examples": ["vertel me het verhaal van Assepoester", "lees me een verhaal voor", "ga verder met het verhaal"],
              "tags": ["entertainment", "verhalen", "orchestrator"]},
    "pt-pt": {"name": "Contador de Histórias",
              "description": "Coordena 'conta-me uma história' entre várias skills contadoras (Andersen, Grimm, Andrew Lang e mais).",
              "examples": ["conta-me a história da Cinderela", "lê-me uma história", "continua a história"],
              "tags": ["entretenimento", "historias", "orchestrator"]},
}

print("Writing adapted/translated files...")
for lang in LANGS:
    dst_dir = COMMON / lang
    dst_dir.mkdir(parents=True, exist_ok=True)

    (dst_dir / "i_know_that.dialog").write_text(I_KNOW_THAT[lang], encoding="utf-8")
    (dst_dir / "from_Tales.dialog").write_text(FROM_TALES[lang], encoding="utf-8")
    (dst_dir / "no_story_providers.dialog").write_text(NO_STORY_PROVIDERS[lang], encoding="utf-8")
    (dst_dir / "no_such_collection.dialog").write_text(NO_SUCH_COLLECTION[lang], encoding="utf-8")
    (dst_dir / "TalesByCollection.intent").write_text(TALES_BY_COLLECTION[lang], encoding="utf-8")

    meta = SKILL_JSON[lang]
    skill_json = {
        "skill_id": "ovos-skill-common-tales.andlo",
        "source": "https://github.com/andlo/ovos-skill-common-tales",
        "package_name": "ovos-skill-common-tales",
        "pip_spec": "ovos-skill-common-tales",
        "license": "GPL-3.0-or-later",
        "author": "andlo",
        "name": meta["name"],
        "description": meta["description"],
        "examples": meta["examples"],
        "tags": meta["tags"],
        "icon": "https://raw.githubusercontent.com/andlo/ovos-skill-common-tales/main/story-512.png",
    }
    with open(dst_dir / "skill.json", "w", encoding="utf-8") as f:
        json.dump(skill_json, f, ensure_ascii=False, indent=2)
        f.write("\n")

print(f"Done. Wrote locale/ for: {', '.join(LANGS)}")
