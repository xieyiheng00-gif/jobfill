"""`/apply <url>`: detect the application system, then fill the form.

Greenhouse, Lever, iCIMS and Ashby are filled by jobfill's own Playwright code (no AI for anything the
database knows). Company portals and other systems are left to the agent's browser; Workday is
recognised but not supported yet (it requires an account login).
"""
