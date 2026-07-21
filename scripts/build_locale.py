#!/usr/bin/env python3
"""Build locale/<lang>/ for ovos-skill-common-reading, generalized from
the earlier common-tales content to cover stories/books/articles/poems,
for all 8 languages (en, da, de, es, fr, it, nl, pt)."""
import json
from pathlib import Path

ROOT = Path("/home/andlo/ovos-skill-common-reading/locale")
LANGS = ["en-us", "da-dk", "de-de", "es-es", "fr-fr", "it-it", "nl-nl", "pt-pt"]

READ_CONTENT_INTENT = {
    "en-us": "(Tell|Read) (me| ) a (good| ) (story|tale|fairy tale|book|article|poem) {title}\n"
             "(Tell|Read) (me| ) the (story|book|article|poem) {title}\n",
    "da-dk": "(Fortæl|Læs) (mig| ) en (god| ) (historie|fortælling|bog|artikel|digt) {title}\n"
             "(Fortæl|Læs) (mig| ) (historien|bogen|artiklen|digtet) {title}\n",
    "de-de": "(Erzähl|Lies) (mir| ) eine (gute| ) (Geschichte|Erzählung|ein Buch|einen Artikel|ein Gedicht) {title}\n"
             "(Erzähl|Lies) (mir| ) (die Geschichte|das Buch|den Artikel|das Gedicht) {title}\n",
    "es-es": "(Cuéntame|Léeme) un (buen| ) (cuento|libro|artículo|poema) {title}\n"
             "(Cuéntame|Léeme) (el cuento|el libro|el artículo|el poema) {title}\n",
    "fr-fr": "(Raconte|Lis)-moi une (bonne| ) (histoire|un livre|un article|un poème) {title}\n"
             "(Raconte|Lis)-moi (l'histoire|le livre|l'article|le poème) {title}\n",
    "it-it": "(Raccontami|Leggimi) una (bella| ) (storia|un libro|un articolo|una poesia) {title}\n"
             "(Raccontami|Leggimi) (la storia|il libro|l'articolo|la poesia) {title}\n",
    "nl-nl": "(Vertel|Lees) (mij| ) een (goed| ) (verhaal|boek|artikel|gedicht) {title}\n"
             "(Vertel|Lees) (mij| ) (het verhaal|het boek|het artikel|het gedicht) {title}\n",
    "pt-pt": "(Conta|Lê)-me (uma boa| ) (história|um livro|um artigo|um poema) {title}\n"
             "(Conta|Lê)-me (a história|o livro|o artigo|o poema) {title}\n",
}

READ_BY_COLLECTION_INTENT = {
    "en-us": "(Tell|Read) (me| ) a (story|book|article|poem) from {collection}\n"
             "(Tell|Read) (me| ) the (story|book|article|poem) {title} from {collection}\n"
             "(Tell|Read) (me| ) a {collection} (story|book|article|poem)\n"
             "(Tell|Read) (me| ) a {collection} (story|book|article|poem) about {title}\n"
             "Find {title} by {collection}\n",
    "da-dk": "(Fortæl|Læs) (mig| ) noget fra {collection}\n"
             "(Fortæl|Læs) (mig| ) {title} fra {collection}\n"
             "(Fortæl|Læs) (mig| ) en {collection}-historie\n"
             "Find {title} af {collection}\n",
    "de-de": "(Erzähl|Lies) (mir| ) etwas von {collection}\n"
             "(Erzähl|Lies) (mir| ) {title} von {collection}\n"
             "(Erzähl|Lies) (mir| ) eine {collection}-Geschichte\n"
             "Finde {title} von {collection}\n",
    "es-es": "(Cuéntame|Léeme) algo de {collection}\n"
             "(Cuéntame|Léeme) {title} de {collection}\n"
             "(Cuéntame|Léeme) un cuento de {collection}\n"
             "Busca {title} de {collection}\n",
    "fr-fr": "(Raconte|Lis)-moi quelque chose de {collection}\n"
             "(Raconte|Lis)-moi {title} de {collection}\n"
             "(Raconte|Lis)-moi une histoire de {collection}\n"
             "Trouve {title} de {collection}\n",
    "it-it": "(Raccontami|Leggimi) qualcosa di {collection}\n"
             "(Raccontami|Leggimi) {title} di {collection}\n"
             "(Raccontami|Leggimi) una storia di {collection}\n"
             "Trova {title} di {collection}\n",
    "nl-nl": "(Vertel|Lees) (mij| ) iets van {collection}\n"
             "(Vertel|Lees) (mij| ) {title} van {collection}\n"
             "(Vertel|Lees) (mij| ) een {collection}-verhaal\n"
             "Zoek {title} van {collection}\n",
    "pt-pt": "(Conta|Lê)-me algo de {collection}\n"
             "(Conta|Lê)-me {title} de {collection}\n"
             "(Conta|Lê)-me uma história de {collection}\n"
             "Encontra {title} de {collection}\n",
}

CONTINUE_INTENT = {
    "en-us": "Continue (telling|reading) (story|fairy tale|tale|book|article|poem)\nContinue (story|reading)\n",
    "da-dk": "Fortsæt (historien|bogen|artiklen|digtet)\nFortsæt\n",
    "de-de": "Erzähl weiter\nMach weiter\n",
    "es-es": "Continúa (el cuento|el libro|el artículo|el poema)\nContinúa\n",
    "fr-fr": "Continue (l'histoire|le livre|l'article|le poème)\nContinue\n",
    "it-it": "Continua (la storia|il libro|l'articolo|la poesia)\nContinua\n",
    "nl-nl": "Ga verder (met het verhaal|met het boek|met het artikel|met het gedicht)\nGa verder\n",
    "pt-pt": "Continua (a história|o livro|o artigo|o poema)\nContinua\n",
}

I_KNOW_THAT = {
    "en-us": "{description}. Let us begin...\nYes, {description}. It goes like this...\n",
    "da-dk": "{description}. Lad os begynde...\nJa, {description}. Den lyder sådan her...\n",
    "de-de": "{description}. Fangen wir an...\nJa, {description}. Sie geht so...\n",
    "es-es": "{description}. Empecemos...\nSí, {description}. Empieza así...\n",
    "fr-fr": "{description}. Commençons...\nOui, {description}. Ça commence comme ça...\n",
    "it-it": "{description}. Cominciamo...\nSì, {description}. Inizia così...\n",
    "nl-nl": "{description}. Laten we beginnen...\nJa, {description}. Het gaat zo...\n",
    "pt-pt": "{description}. Vamos começar...\nSim, {description}. Começa assim...\n",
}

IS_IT_THAT = {
    "en-us": "Is it that one?\nCould it be that?\nShall I read you this one?\nDo you want to hear that?\n",
    "da-dk": "Er det den?\nKunne det være den?\nSkal jeg læse den for dig?\nVil du høre den?\n",
    "de-de": "Ist es diese?\nKönnte es diese sein?\nSoll ich dir diese vorlesen?\nMöchtest du diese hören?\n",
    "es-es": "¿Es ese?\n¿Podría ser ese?\n¿Quieres que te lea ese?\n¿Quieres escuchar ese?\n",
    "fr-fr": "Est-ce celui-là ?\nSerait-ce celui-là ?\nVeux-tu que je te lise celui-là ?\nVeux-tu entendre celui-là ?\n",
    "it-it": "È questo?\nPotrebbe essere questo?\nVuoi che te lo legga?\nVuoi ascoltarlo?\n",
    "nl-nl": "Is het die?\nZou het die kunnen zijn?\nZal ik je die voorlezen?\nWil je die horen?\n",
    "pt-pt": "É esse?\nPodia ser esse?\nQueres que te leia esse?\nQueres ouvir esse?\n",
}

THAT_WOULD_BE = {
    "en-us": "I can read you {title}.\nI remember {title}.\n",
    "da-dk": "Jeg kan læse {title} for dig.\nJeg kender {title}.\n",
    "de-de": "Ich kann dir {title} vorlesen.\nIch kenne {title}.\n",
    "es-es": "Puedo leerte {title}.\nMe acuerdo de {title}.\n",
    "fr-fr": "Je peux te lire {title}.\nJe me souviens de {title}.\n",
    "it-it": "Posso leggerti {title}.\nMi ricordo {title}.\n",
    "nl-nl": "Ik kan je {title} voorlezen.\nIk herinner me {title}.\n",
    "pt-pt": "Posso ler-te {title}.\nLembro-me de {title}.\n",
}

NO_CONTENT = {
    "en-us": "Then I don't know what you'd like me to read.\n",
    "da-dk": "Så ved jeg ikke, hvad du vil have mig til at læse.\n",
    "de-de": "Dann weiß ich nicht, was ich dir vorlesen soll.\n",
    "es-es": "Entonces no sé qué quieres que te lea.\n",
    "fr-fr": "Alors je ne sais pas ce que tu veux que je te lise.\n",
    "it-it": "Allora non so cosa vuoi che ti legga.\n",
    "nl-nl": "Dan weet ik niet wat je wilt dat ik voorlees.\n",
    "pt-pt": "Então não sei o que queres que eu te leia.\n",
}

NOTHING_TO_CONTINUE = {
    "en-us": "You don't have anything in progress for me to continue.\n",
    "da-dk": "Du har ikke noget i gang, som jeg kan fortsætte.\n",
    "de-de": "Du hast gerade nichts, das ich fortsetzen kann.\n",
    "es-es": "No tienes nada a medias para continuar.\n",
    "fr-fr": "Tu n'as rien en cours à continuer.\n",
    "it-it": "Non hai niente in corso da continuare.\n",
    "nl-nl": "Je hebt niets dat ik kan voortzetten.\n",
    "pt-pt": "Não tens nada em curso para eu continuar.\n",
}

CONTINUE_DIALOG = {
    "en-us": "Continuing {title}\nWhere did we get to. Oh yes, here. {title}\n",
    "da-dk": "Fortsætter {title}\nHvor kom vi til. Nå ja, her. {title}\n",
    "de-de": "Ich mache weiter mit {title}\nWo waren wir stehen geblieben. Ach ja, hier. {title}\n",
    "es-es": "Continúo con {title}\n¿Dónde nos quedamos? Ah sí, aquí. {title}\n",
    "fr-fr": "Je continue avec {title}\nOù en étions-nous. Ah oui, ici. {title}\n",
    "it-it": "Continuo con {title}\nDove eravamo rimasti. Ah sì, qui. {title}\n",
    "nl-nl": "Ik ga verder met {title}\nWaar waren we gebleven. Oh ja, hier. {title}\n",
    "pt-pt": "Continuo com {title}\nOnde é que ficámos. Ah sim, aqui. {title}\n",
}

STOP_READING = {
    "en-us": "Ok. I'll stop reading for now.\nFine. We can continue another time.\n",
    "da-dk": "Ok. Jeg stopper med at læse for nu.\nFint. Vi kan fortsætte en anden gang.\n",
    "de-de": "Ok. Ich höre für jetzt auf zu lesen.\nGut. Wir können ein andermal weitermachen.\n",
    "es-es": "Vale. Dejo de leer por ahora.\nBien. Podemos continuar en otro momento.\n",
    "fr-fr": "D'accord. J'arrête de lire pour l'instant.\nTrès bien. On pourra continuer une autre fois.\n",
    "it-it": "Ok. Per ora smetto di leggere.\nVa bene. Possiamo continuare un'altra volta.\n",
    "nl-nl": "Oké. Ik stop met voorlezen voor nu.\nPrima. We kunnen een andere keer verdergaan.\n",
    "pt-pt": "Ok. Paro de ler por agora.\nEstá bem. Podemos continuar noutra altura.\n",
}

CONTENT_UNAVAILABLE = {
    "en-us": "Sorry, I couldn't reach that right now. Please try again in a moment.\n",
    "da-dk": "Beklager, jeg kunne ikke hente det lige nu. Prøv igen om lidt.\n",
    "de-de": "Entschuldigung, ich konnte das gerade nicht abrufen. Bitte versuche es gleich noch einmal.\n",
    "es-es": "Lo siento, no he podido acceder a eso ahora mismo. Inténtalo de nuevo en un momento.\n",
    "fr-fr": "Désolé, je n'ai pas pu y accéder pour le moment. Réessaie dans un instant.\n",
    "it-it": "Mi dispiace, non sono riuscito a recuperarlo in questo momento. Riprova tra poco.\n",
    "nl-nl": "Sorry, ik kon dat nu niet ophalen. Probeer het straks nog eens.\n",
    "pt-pt": "Desculpa, não consegui aceder a isso agora. Tenta de novo daqui a pouco.\n",
}

NO_CONTENT_PROVIDERS = {
    "en-us": "I don't have anything installed to read to you right now.\n",
    "da-dk": "Jeg har ikke noget installeret, som jeg kan læse op for dig lige nu.\n",
    "de-de": "Ich habe gerade nichts installiert, das ich dir vorlesen könnte.\n",
    "es-es": "Ahora mismo no tengo nada instalado que pueda leerte.\n",
    "fr-fr": "Je n'ai actuellement rien d'installé à te lire.\n",
    "it-it": "Al momento non ho nulla di installato da leggerti.\n",
    "nl-nl": "Ik heb op dit moment niets geïnstalleerd om je voor te lezen.\n",
    "pt-pt": "Não tenho nada instalado para te ler agora.\n",
}

NO_SUCH_COLLECTION = {
    "en-us": "I don't know a source called {collection}.\nI don't have anything from {collection}.\n",
    "da-dk": "Jeg kender ikke en kilde ved navn {collection}.\nJeg har ikke noget fra {collection}.\n",
    "de-de": "Ich kenne keine Quelle namens {collection}.\nIch habe nichts von {collection}.\n",
    "es-es": "No conozco ninguna fuente llamada {collection}.\nNo tengo nada de {collection}.\n",
    "fr-fr": "Je ne connais pas de source appelée {collection}.\nJe n'ai rien de {collection}.\n",
    "it-it": "Non conosco nessuna fonte chiamata {collection}.\nNon ho nulla di {collection}.\n",
    "nl-nl": "Ik ken geen bron die {collection} heet.\nIk heb niets van {collection}.\n",
    "pt-pt": "Não conheço nenhuma fonte chamada {collection}.\nNão tenho nada de {collection}.\n",
}

FINISHED_READING = {
    "en-us": "This was read to you from {source}.\n",
    "da-dk": "Dette blev læst op for dig fra {source}.\n",
    "de-de": "Dies wurde dir aus {source} vorgelesen.\n",
    "es-es": "Esto te lo he leído de {source}.\n",
    "fr-fr": "Ceci t'a été lu depuis {source}.\n",
    "it-it": "Questo ti è stato letto da {source}.\n",
    "nl-nl": "Dit werd aan je voorgelezen van {source}.\n",
    "pt-pt": "Isto foi-lhe lido a partir de {source}.\n",
}

SKILL_JSON = {
    "en-us": {"name": "Common Reading",
              "description": "Orchestrates 'read me something' across content provider skills (fairy tales, books, articles and more), similar to how OCP orchestrates media playback.",
              "examples": ["tell me a story about Cinderella", "read me a story from Grimm", "continue"],
              "tags": ["entertainment", "reading", "stories", "orchestrator"]},
    "da-dk": {"name": "Fælles Læsning",
              "description": "Formidler 'læs noget for mig' på tværs af indholds-skills (eventyr, bøger, artikler og mere).",
              "examples": ["fortæl historien om Askepot", "læs en historie fra Grimm", "fortsæt"],
              "tags": ["underholdning", "laesning", "historier", "orchestrator"]},
    "de-de": {"name": "Gemeinsames Lesen",
              "description": "Vermittelt 'lies mir etwas vor' über mehrere Inhalts-Skills (Märchen, Bücher, Artikel und mehr).",
              "examples": ["erzähl mir das Märchen Aschenputtel", "lies mir eine Geschichte von Grimm vor", "mach weiter"],
              "tags": ["unterhaltung", "lesen", "geschichten", "orchestrator"]},
    "es-es": {"name": "Lectura Común",
              "description": "Coordina 'léeme algo' entre varias skills de contenido (cuentos, libros, artículos y más).",
              "examples": ["cuéntame el cuento de Cenicienta", "léeme un cuento de Grimm", "continúa"],
              "tags": ["entretenimiento", "lectura", "cuentos", "orchestrator"]},
    "fr-fr": {"name": "Lecture Commune",
              "description": "Coordonne « lis-moi quelque chose » entre plusieurs skills de contenu (contes, livres, articles et plus).",
              "examples": ["raconte-moi l'histoire de Cendrillon", "lis-moi une histoire de Grimm", "continue"],
              "tags": ["divertissement", "lecture", "histoires", "orchestrator"]},
    "it-it": {"name": "Lettura Comune",
              "description": "Coordina 'leggimi qualcosa' tra più skill di contenuto (fiabe, libri, articoli e altro).",
              "examples": ["raccontami la storia di Cenerentola", "leggimi una storia di Grimm", "continua"],
              "tags": ["intrattenimento", "lettura", "storie", "orchestrator"]},
    "nl-nl": {"name": "Gedeeld Voorlezen",
              "description": "Coördineert 'lees me iets voor' tussen meerdere content-skills (sprookjes, boeken, artikelen en meer).",
              "examples": ["vertel me het verhaal van Assepoester", "lees me een verhaal van Grimm voor", "ga verder"],
              "tags": ["entertainment", "voorlezen", "verhalen", "orchestrator"]},
    "pt-pt": {"name": "Leitura Comum",
              "description": "Coordena 'lê-me algo' entre várias skills de conteúdo (contos, livros, artigos e mais).",
              "examples": ["conta-me a história da Cinderela", "lê-me uma história de Grimm", "continua"],
              "tags": ["entretenimento", "leitura", "historias", "orchestrator"]},
}

def main():
    for lang in LANGS:
        d = ROOT / lang
        d.mkdir(parents=True, exist_ok=True)

        (d / "ReadContent.intent").write_text(READ_CONTENT_INTENT[lang], encoding="utf-8")
        (d / "ReadContentByCollection.intent").write_text(READ_BY_COLLECTION_INTENT[lang], encoding="utf-8")
        (d / "continue.intent").write_text(CONTINUE_INTENT[lang], encoding="utf-8")
        (d / "i_know_that.dialog").write_text(I_KNOW_THAT[lang], encoding="utf-8")
        (d / "is_it_that.dialog").write_text(IS_IT_THAT[lang], encoding="utf-8")
        (d / "that_would_be.dialog").write_text(THAT_WOULD_BE[lang], encoding="utf-8")
        (d / "no_content.dialog").write_text(NO_CONTENT[lang], encoding="utf-8")
        (d / "nothing_to_continue.dialog").write_text(NOTHING_TO_CONTINUE[lang], encoding="utf-8")
        (d / "continue.dialog").write_text(CONTINUE_DIALOG[lang], encoding="utf-8")
        (d / "stop_reading.dialog").write_text(STOP_READING[lang], encoding="utf-8")
        (d / "content_unavailable.dialog").write_text(CONTENT_UNAVAILABLE[lang], encoding="utf-8")
        (d / "no_content_providers.dialog").write_text(NO_CONTENT_PROVIDERS[lang], encoding="utf-8")
        (d / "no_such_collection.dialog").write_text(NO_SUCH_COLLECTION[lang], encoding="utf-8")
        (d / "finished_reading.dialog").write_text(FINISHED_READING[lang], encoding="utf-8")

        meta = SKILL_JSON[lang]
        skill_json = {
            "skill_id": "ovos-skill-common-reading.andlo",
            "source": "https://github.com/andlo/ovos-skill-common-reading",
            "package_name": "ovos-skill-common-reading",
            "pip_spec": "ovos-skill-common-reading",
            "license": "GPL-3.0-or-later",
            "author": "andlo",
            "name": meta["name"],
            "description": meta["description"],
            "examples": meta["examples"],
            "tags": meta["tags"],
            "icon": "https://raw.githubusercontent.com/andlo/ovos-skill-common-reading/main/story-512.png",
        }
        with open(d / "skill.json", "w", encoding="utf-8") as f:
            json.dump(skill_json, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print(f"Wrote locale/ for: {', '.join(LANGS)}")


if __name__ == "__main__":
    main()
