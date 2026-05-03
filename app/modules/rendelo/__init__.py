"""Rendelő modul: belső igénytracker.

Az `app.shared.models`-ben élő `User`/`UserSession`/`Invite` táblákra
épül. A modul-saját táblák (`rendelo_categories`, `rendelo_items`,
`rendelo_requests`, `rendelo_request_lines`, `rendelo_events`) a
`models.py`-ban vannak deklarálva.

A modul fő route prefixe `/rendelo`, és csak a `is_orderer`,
`is_workshop`, `is_designer` vagy `is_admin` flag-gel rendelkező user
fér hozzá (lásd `app.shared.sidebar.MODULES`).
"""
