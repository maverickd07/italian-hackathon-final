The challenge
Every day thousands of companies still keep their clients, contacts and deals in CRMs that show their age. In this final you build a new one, starting from an empty repo: a CRM with an API compatible with HubSpot CRM and an interface to use it. Then the touch that makes it of its time: an AI assistant in chat that works inside the CRM, its only AI feature and a real part of the challenge. Write it with whatever tools you like.

Your CRM already has its first client: Brambilla Forniture S.p.A., with fifteen years of data inside a CRM that is about to be switched off. It has to take all of it in without losing a single record, and the next day Brambilla works on it, asking the assistant for things too.

Get as much as you can working. There is more work here than we expect anyone to finish in five hours: what counts is what works at 15:30, and choosing where to start is part of the race.

We test your CRM from outside, against your deploy. The tests check that Brambilla's requests are met, looking at the outcomes on the data and on the CRM's behavior; that the assistant handles well requests nobody has seen before; that the CRM behaves as HubSpot's documentation describes; and that it holds up as a system a company actually works on.

The client
Brambilla Forniture S.p.A., a distributor of industrial supplies. Its customers, contacts, deals, quotes, support tickets and activities have lived for fifteen years in Sinergia 4, an on-premise CRM that is being switched off.

Brambilla has written down what it needs, in its own words: thirteen requests, from the data to bring over to the rules, the numbers, how the CRM has to work, and the assistant its sales reps talk to. The requests don't say how to handle every shape the data is written in: that you work out from the data.

Brambilla is an Italian company, so what comes from it is in Italian: the requests in RICHIESTE.md, the Sinergia export and the messages its sales reps send to the assistant. The names in the requests' appendix are used by the tests verbatim. Here the requests are translated.

Where a request doesn't say something, look at the data: everything you need to understand what it has to become is always in there.

Brambilla Forniture, the requests
R1
Companies
A company exists only once, and keeps the websites of the records merged into it.
R2
People
A person exists only once, associated with their company.
R3
Deals
Amount, currency, pipeline, stage, sales rep and associations of every deal.
R4
Price list and quotes
The price list becomes products, quote lines become associated line items.
R5
Support
Tickets in the Assistenza pipeline, with their owner and their associations.
R6
History
Activities become notes, calls, emails and meetings.
R7
The VAT number
The VAT number is unique: the CRM rejects a duplicate with 409.
R8
2025 revenue and class
Revenue won in 2025 and the A, B or C class of every company.
R9
Dormant customers
The list of companies that have won deals but had no activity in 2025.
R10
Deal won, supply kickoff
Deal won: the supply kickoff ticket opens.
R11
Deal lost, follow-up call
Deal lost: a task to call back in six months.
R12
The contact finds its company
A contact without a company finds it from their email domain.
R13
The assistant
A chat assistant that runs operations, answers questions and knows when not to act. Two examples among the materials.
The full text, with the exact names of properties, pipelines and stages, is in RICHIESTE.md, among the materials.

The assistant
Your CRM has a chat assistant: request R13, where Brambilla says what it has to be able to do. A Brambilla sales rep writes to it in Italian asking for what they need, and the assistant either does it on the CRM or answers. Here is how we talk to it and how we score it.

The model
The assistant uses only openai/gpt-6-luna on OpenRouter, with the key you find in Deploy and put in the OPENROUTER_API_KEY variable of your service. The key works only with that model and has a spending cap of $10 for the whole day, development and evaluation together: keep a margin, because a key used up while trying things out leaves the assistant silent in the evaluation. Tools, prompt and logic around the model are yours.

The contract
POST /__agente, with the token like every other call. No state is kept, on either side: every turn sends the whole conversation so far. context.now is the moment of the request ("today", "six months from now" count from there, not from the server's clock), context.user is who is writing, an active user from utenti.csv ("my customers" are theirs). Attachments are text only: a CSV in the content field, with Sinergia's ; separator.

The request
{
  "context": {
    "now": "2026-12-02T10:00:00+01:00",
    "user": "anna.sala@brambillaforniture.it"
  },
  "messages": [
    {
      "role": "user",
      "content": "Ti allego il nuovo listino, aggiorna i prodotti",
      "attachments": [
        { "name": "listino.csv", "content_type": "text/csv", "content": "..." }
      ]
    },
    { "role": "assistant", "content": "..." },
    { "role": "user", "content": "..." }
  ]
}
It replies 200 with the text for the sales rep, within 60 seconds per turn: past that, the turn counts as an empty reply. Conversations arrive 4 at a time, each on its own records.

The reply
{ "reply": "<text in Italian>" }
How it's scored
After the suite, on the same frozen deploy. First a POST /__reset and the migration of a small, clean export kept for the evaluation: the same nine CSV files, a few hundred rows, no duplicates and none of the shapes the requests don't describe. We check that it arrived, record by id_legacy: a request that touches records that are missing is worth zero.

Then about 40 requests never seen before, in the voice of Brambilla's employees, each on its own records. A Brambilla colleague, simulated by a model of ours, opens the conversation and after each reply decides whether to answer or close. They know what their request needs and say it when asked; they close when the assistant says it is done, says it can't, or asks something they don't know.

Each request has a cap on turns, each turn 60 seconds, all the requests for your CRM together 30 minutes: when a cap trips, we score the CRM as it is at that moment. After each conversation we read the request's records through the API and compare them with the expected outcome; at the end of the round we check that the records no request was supposed to touch are as they were. What the CRM's automations do (R10, R11, R12) doesn't count as damage.

Operations, 2/3 of the points: the state of the CRM after the conversation. Each request is worth the share of its checks that pass; a record of the request changed where it shouldn't have been sends it to zero.
Questions, 23%: the expected facts (numbers, names, emails) in the reply. Numbers count in Italian or English form: 12.345,67 and 12345.67.
Quality, 10%: a judge model reads the conversation for clarity, facts that are real, and saying when it can't.
A request that must not be carried out as it stands counts among operations and questions: the CRM stays as it was, and the reply says why. The assistant can ask questions freely; asking for something already written in the request weighs only on quality.

Two example requests, with who writes them and when, are in assistant/examples.md among the materials. The evaluation's requests are different ones, on the scenario above.

What you get
From 10:30, in Materials. starter.zip holds everything, in the folders named here.

The Sinergia export (legacy/export.zip): nine CSV files, companies, contacts, deals, quote lines, price list, tickets, activities, users and stage history, about 675,000 rows.
Brambilla's requests (legacy/RICHIESTE.md): what it needs, in its own words, with an appendix of the names the tests use. The data always contains what you need for the cases they don't describe.
The assistant's examples (assistant/examples.md), the choice sheet template (CHOICE-SHEET.md), the FAQ (FAQ.md) and this brief as a file (BRIEF.md).
HubSpot's public documentation, version 2026-09, the one the site shows by default. Every reference page contains the OpenAPI of its endpoint. Index for agents: developers.hubspot.com/docs/llms.txt. The links picked module by module are at the bottom.
Your CRM token and the model key for the assistant, in Deploy.
The export you get is a full Sinergia export. In the evaluation your CRM migrates another export from the same Sinergia: same rules, same size, different data.

The technical rules
Authentication. Every test call carries Authorization: Bearer <your token>, like a HubSpot private app. We give you the token, in Deploy: put it in a variable of your service. Without a valid token, 401. Only GET /health and the links to export files answer without a token, like HubSpot's signed links: the file at the address in result of a completed export's status downloads without a token (a relative address resolves on your CRM).
POST /__reset. Brings the CRM back to the state of a freshly created HubSpot account: no records, the default properties, pipelines and association types the documentation describes, and the rate-limit counters back to zero. The properties, pipelines and list Brambilla asks for are created by the migration. Replies 204. Requires the token. The tests call it before every isolated test, hundreds of times in a round: it has to be fast.
POST /__migrate. Body {"export_url": "https://..."}. The CRM downloads the archive at that address, migrates it according to Brambilla's requests and replies 204 when it is done: from then on the data, the figures of R8 and the list of R9 can be read through the API. It has 5 minutes: Railway closes with a 502 a request that gets no response for 5 minutes. On Railway the same migration can take twice as long from one run to the next: measure it on your deploy with the form check and keep a wide margin. Requires the token. The tests call it once, right after a POST /__reset. The address can be http or https and have parameters: download what is there, whatever the file is called. Activities become HubSpot activity objects (notes, calls, emails, meetings), the price list becomes products, quote lines become line items, tickets become tickets, all with their associations.
GET /health. No token. Replies 200 with {"status": "ok", "version": "2026-09", "ui": {"contacts": "/contacts", ...}}: in ui, every module that has a page, with its route.
The deploy. The CRM runs in a Railway project of ours, one per finalist: at the kickoff, at 09:45, you get an email inviting you to it as an Editor. Deploy there and register the service's https address in Deploy. Keep the project's region, EU West: the tests run from Europe and make thousands of calls, and a CRM in the US answers each one 100 ms later. You can change the address until 15:30; after that we evaluate the CRM that answers there.
Timeouts. Every test call waits at most 10 seconds, except /__migrate (5 minutes) and /__agente (60 seconds): past that, it counts as failed.
POST /__agente. The assistant, with the contract in the assistant section.
How we read your CRM
The checks read and write the CRM only through its API, like a HubSpot integration: what they score is what the API shows. Automations (R10, R11, R12) can work asynchronously: the checks wait up to 15 seconds for their effect to show. A date or an instant is read as ISO 8601 or as milliseconds, a number as a string or as a number.

What holding up means
A company will be working on it from the next day. At the end of the race, on the CRM after the migration of the hidden export, we check that:

data survives: we restart the service, and what was there before is still there;
concurrent writes don't get lost: parallel updates of the same record, parallel creates, parallel upserts on the same email produce no duplicates and lose no values;
pagination and search hold up on the migrated volume: every record exactly once, exact totals. As in HubSpot, a record just written can show up in search with a delay: on the migrated volume the checks wait up to 15 seconds, in the conformity tests 3;
reads are fast under load: with 20 clients in parallel, 95% of single-record reads answer in under 1 second and none answers with a 5xx error.
All of these checks work on the migrated CRM: durability needs a successful migration.

What counts
The test score is out of 100, split into 4 sections. Each part is worth the share of its checks you pass, partial credit included.

Brambilla's requests
50points
R1Companies
4
R2People
4
R3Deals
6
R4Price list and quotes
4
R5Support
4
R6History
4
R7The VAT number
4
R82025 revenue and class
6
R9Dormant customers
4
R10Deal won, supply kickoff
4
R11Deal lost, follow-up call
3
R12The contact finds its company
3
The assistant
30points
Operations
20.1
Questions
6.9
Quality of the replies
3
API conformity
10points
Deals and pipelines
1.53
Contacts
1.33
Associations
1.22
Search
1.22
Properties
1.02
Companies
0.92
Activities
0.82
Tickets
0.61
Lists
0.61
Products and quotes
0.41
Imports and exports
0.31
Durability
10points
Paging and search on the migrated volume
4.55
Concurrent writes are not lost
3.64
Fast reads under load
0.91
Data survives a restart
0.91
The data requests (R1-R9) are checked after POST /__migrate of the hidden export, reading the whole CRM through the API and comparing it record by record with what Brambilla expects. In requests R1-R6 half the points go to records and fields, half to the cases the requests don't describe and that you discover in the data. The behavior requests create and edit records through the API after the migration and watch what the CRM does: R10 and R11 only that way, R7 and R12 on the migrated data too.

Conformity covers the modules of the links at the bottom.

The interface, in English, has no tests: the jury judges it for the top 6, with the company page, the deals board, the dormant customers list and the tickets.

How scoring works
During the race you run a form check of your deploy from Form check whenever you like: it responds, /health is right, the token is accepted, /__reset and /__migrate respond as they should, /__agente replies in the contract's format, and a few example tests pass. For every check that fails you see what we called and what you answered. Some things, like the migration's timing, only show on the deploy: it pays to have one early.
From 15:00 to 15:30 you fill in the choice sheet in Choices: what you found in the data that the requests didn't say, how you handled it and why, what you didn't do.
At 15:30 deploys freeze and the full suite (conformity, migration of the hidden export, requests, durability) runs on every CRM, once. Then, on the same deploy, the assistant's evaluation.
The ranking is revealed at the award ceremony, at 16:30.
The top 6 by test score are judged by the jury on three axes, each out of 10: the interface, the choices on the cases the requests don't describe (the choice sheet), the product. Their final score is 80% tests and 20% jury: the tests are worth 80 points out of 100, the jury 20. The top 6 stay the top 6: the jury reorders them. The top 3 of the final ranking present their CRM at the award ceremony, in an 8-minute pitch.
The rules
One per person.
You start from an empty repo at 10:30. The code is written during the race, by you and your agents; libraries and frameworks are fine.
From 15:30 the deploy stays as it is until the evaluation is over: no push, redeploy or changed variables.
Any tools you like to write the code; inside the CRM the only AI feature is the assistant, with the model and the key we give you.
No HubSpot name or logo in your app.
Links by module
Module
API
How to use it in the UI
Contacts
guide
record list
record page
merge
Companies
guide
domains
deduplication
Deals
guide
board
default properties
Pipelines
guide
pipelines and stages
Associations
records
schema
associate records
labels
Properties
guide
create and edit
field types
groups
Search
guide
search
filters
Activities
notes
calls
emails
meetings
tasks
log activities
timeline
Tickets
guide
manage tickets
default properties
Lists
guide
filters
create a list
Products
products
line items
quotes
products
line items in deals
Import and export
import
export
import
export
Errors
error handling
