"""Munkák modul: ügyfélmunka pipeline.

Felvételtől átadásig követi az ügyfélmunkákat. Adatmodellek:
`jobs`, `job_tasks`, `job_attachments` (mind `jobs_*` prefixszel a DB-ben).

A modul támaszkodik a `app.shared.models.Customer` táblára (közös, később
a printbt.hu redesign is olvasná). A `users` szintén közös.

A modul fő route-prefixe `/jobs`. A felvevő-jogos (`is_intake`) user adhat
fel új munkát, a grafikus (`is_designer`) dolgozik rajta, a műhelyes
(`is_workshop`) végzi a fizikai munkát, és az admin mindent.
"""
