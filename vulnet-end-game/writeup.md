# VulnNet Endgame Writeup

**Machine Name:** VulnNet Endgame  
**Platform:** TryHackMe  
**Difficulty:** Medium

---

![display](screenshots/display.jpg)

## Introduction

This write up covers VulnNet Endgame. Unlike a lot of easy boxes that hand over a vulnerability in the first port scan, this one only opens with two ports: SSH and HTTP. Everything else has to be earned through enumeration, which is exactly the hint the room description gives.

The path here is longer than most. A hidden subdomain leads to a blog, the blog leads to an internal API, the API is injectable, and the database behind that injection leaks two different sets of credentials at once. One of those credential sets unlocks a CMS admin panel, which becomes the entry point for code execution. From there, the box still has one more twist waiting at the privilege escalation stage. Nothing here is a single lucky exploit. It is a chain, and missing any one link means starting over.

## Phase 1: Enumeration

Started with a full TCP port scan against the target.

> nmap -p- -sV -sC <TARGET_IP>

Only two ports were open: port 22 running OpenSSH 7.6p1 on Ubuntu, and port 80 running Apache 2.4.29. The HTTP service did not return a page title, and visiting the IP directly in the browser confirmed why: the application only responds when it is reached through its proper hostname.

![access denied direct ip](screenshots/access-denied-direct-ip.png)

After adding the domain to the hosts file, the root page turned out to be a generic "coming soon" landing template, nothing that pointed anywhere useful on its own.

![coming soon page](screenshots/coming-soon-page.png)

A directory scan against the root domain came back mostly empty: a few static asset folders and a stray README.txt describing the HTML template in use. No admin panel, no obvious entry point.

![dirsearch root](screenshots/dirsearch-root.png)
![images directory listing](screenshots/images-directory-listing.png)
![readme txt](screenshots/readme-txt.png)

> **Security Issue #1:** Minimal Attack Surface on the Main Host. The root domain gave away almost nothing, which meant the real application lived somewhere else in the domain structure.

## Phase 2: Subdomain Discovery

With the main site being a dead end, the next move was hunting for subdomains. Passive enumeration with Amass returned nothing.

![amass enum command](screenshots/amass-enum-command.png)
![amass no assets](screenshots/amass-no-assets.png)

Switching to active brute forcing with ffuf against the Host header turned up four live subdomains: **shop**, **api**, **blog**, and **admin1**.

![ffuf subdomain bruteforce](screenshots/ffuf-subdomain-bruteforce.png)

> **Security Issue #2:** Sensitive Subdomains Not Blocked From Discovery. An admin panel and an internal API were both reachable simply by guessing hostnames. Neither required any prior authentication just to confirm they existed.

## Phase 3: SQL Injection Through the Blog

The blog subdomain hosted a simple set of posts. Viewing the page source of the first post revealed a script pulling content dynamically from an internal endpoint under `api.vulnnet.thm/vn_internals/`.

![blog homepage](screenshots/blog-homepage.png)
![blog post page](screenshots/blog-post-page.png)
![blog post source snippet](screenshots/blog-post-source-snippet.png)
![api fetch endpoint](screenshots/api-fetch-endpoint.png)

The endpoint took a `blog` parameter. A quick boolean test (`?blog=1 or 1=1`) returned the same result regardless of the true value, a classic sign of SQL injection.

![api sqli test](screenshots/api-sqli-test.png)

Running sqlmap against the parameter confirmed it: boolean based, time based, and UNION based injection were all possible, and the backend was identified as MySQL. Two databases were exposed alongside the default schemas: **vn_admin** and **blog**.

![sqlmap command](screenshots/sqlmap-command.png)
![sqlmap vulnerable param](screenshots/sqlmap-vulnerable-param.png)
![sqlmap dbs found](screenshots/sqlmap-dbs-found.png)

> **Security Issue #3:** Unauthenticated SQL Injection on an Internal API. A parameter meant only to fetch a blog post by ID accepted raw, unsanitized input and exposed the entire underlying database to anyone who found the endpoint.

## Phase 4: Harvesting and Cracking Credentials

The `vn_admin` database held tables belonging to a CMS install, including `be_users`. Dumping the `username` and `password` columns from that table returned a single admin account, `chris_w`, protected by an Argon2 hash.

![vn admin tables](screenshots/vn-admin-tables.png)
![be users columns command](screenshots/be-users-columns-command.png)
![be users columns list](screenshots/be-users-columns-list.png)
![be users dump command](screenshots/be-users-dump-command.png)
![be users credentials](screenshots/be-users-credentials.png)

That hash alone was not immediately crackable with a standard wordlist. So the second database, `blog`, was dumped as well. Its `users` table held a long list of usernames and plaintext-style passwords, good enough to build a custom wordlist and throw at the admin hash.

![blog tables command](screenshots/blog-tables-command.png)
![blog tables list](screenshots/blog-tables-list.png)
![blog users columns command](screenshots/blog-users-columns-command.png)
![blog users columns list](screenshots/blog-users-columns-list.png)
![blog users dump command](screenshots/blog-users-dump-command.png)
![blog users passwords](screenshots/blog-users-passwords.png)
![hash and wordlist files](screenshots/hash-and-wordlist-files.png)

Running John the Ripper against the admin hash using that dumped password list cracked it in under a minute.

![john cracked password](screenshots/john-cracked-password.png)

> **Security Issue #4:** Password Reuse Made Cracking Trivial. The admin account's password was not unique. It matched a pattern already present in another table on the same server, which meant one leaked dataset directly compromised a second, unrelated account.

## Phase 5: Admin Access and Remote Code Execution

The other two subdomains were checked along the way. Shop was a static storefront template with no working login, and the raw API and admin1 roots just returned status banners.

![shop subdomain](screenshots/shop-subdomain.png)
![api subdomain root](screenshots/api-subdomain-root.png)
![admin1 subdomain root](screenshots/admin1-subdomain-root.png)

A directory scan against admin1 revealed a TYPO3 CMS installation.

![dirsearch admin1](screenshots/dirsearch-admin1.png)
![typo3 login page](screenshots/typo3-login-page.png)

Logging in with the cracked `chris_w` credentials worked immediately, landing on a full TYPO3 backend dashboard.

![typo3 admin dashboard](screenshots/typo3-admin-dashboard.png)

TYPO3's file module allowed uploads into the `fileadmin` folder. A PHP reverse shell was rejected outright by the extension filter.

![fileadmin folder](screenshots/fileadmin-folder.png)
![upload blocked extension](screenshots/upload-blocked-extension.png)

Checking the backend's deny pattern configuration showed exactly which extensions were blocked and how the filter was built, which made it possible to work out a file name that would slip past it.

![filedenypattern config 1](screenshots/filedenypattern-config-1.png)
![install tool settings](screenshots/install-tool-settings.png)
![filedenypattern config 2](screenshots/filedenypattern-config-2.png)

With a renamed payload, the upload succeeded and the file became reachable directly from the web root.

![renamed shell uploaded](screenshots/renamed-shell-uploaded.png)
![fileadmin index listing](screenshots/fileadmin-index-listing.png)

> **Security Issue #5:** Authenticated File Upload Led Straight to Code Execution. Once inside the admin panel, the only thing standing between a logged in user and a shell was an extension blocklist, and blocklists are made to be bypassed.

## Phase 6: Reverse Shell and Lateral Movement

With a listener ready, requesting the uploaded file triggered a working reverse shell as `www-data`.

![netcat listener](screenshots/netcat-listener.png)
![reverse shell connected](screenshots/reverse-shell-connected.png)

Enumerating `/home` revealed a second user named `system`. The user flag lived inside that account's home directory, out of reach for `www-data`. Instead of a flag file sitting in the open, the way in came from that user's browser data: a `.mozilla` Firefox profile folder was zipped up and served out over a temporary HTTP server so it could be pulled to the attacking machine.

![home directory enum](screenshots/home-directory-enum.png)
![zip mozilla folder](screenshots/zip-mozilla-folder.png)
![mozip ls](screenshots/mozip-ls.png)
![python http server](screenshots/python-http-server.png)
![download mozip](screenshots/download-mozip.png)

Inside the archive were two Firefox profiles. Only one had saved logins.

![firefox profiles listing](screenshots/firefox-profiles-listing.png)
![profile folder contents](screenshots/profile-folder-contents.png)
![profiles ini](screenshots/profiles-ini.png)

Running that profile through firefox_decrypt recovered a saved login for `tryhackme.com`: the credentials belonging to the `system` user.

![firefox decrypt credentials](screenshots/firefox-decrypt-credentials.png)

### Flag 1

Those credentials logged in over SSH as `system`, and from there the user flag was sitting in the home directory.

![ssh login system user](screenshots/ssh-login-system-user.png)
![user flag](screenshots/user-flag.png)

> **Security Issue #6:** Credentials Saved in a Local Browser Profile. A password manager built into a browser is only as safe as the machine it sits on. Once an attacker has any foothold on that machine, saved logins are just another file to steal and decrypt offline.

## Phase 7: Privilege Escalation to Root

Checking Linux capabilities on binaries owned by the `system` user with `getcap` showed something unusual: `/home/system/Utils/openssl` had the `cap_setuid,cap_setgid+ep` capability set, despite not being a SUID binary and not being owned by root.

![getcap openssl capability](screenshots/getcap-openssl-capability.png)
![openssl binary permissions](screenshots/openssl-binary-permissions.png)

That combination is enough for arbitrary code execution as root through openssl's engine loading feature. A small C payload was written to call `setuid(0)`, `setgid(0)`, and spawn a shell, then compiled into a shared object.

![exploit c source](screenshots/exploit-c-source.png)
![compile exploit](screenshots/compile-exploit.png)

The compiled object was served over HTTP, pulled onto the target, moved into `/tmp`, and made executable.

![serve exploit http](screenshots/serve-exploit-http.png)
![download exploit target](screenshots/download-exploit-target.png)
![move exploit tmp](screenshots/move-exploit-tmp.png)
![chmod exploit](screenshots/chmod-exploit.png)

Loading it as an engine through the capability-enabled openssl binary dropped straight into a root shell.

![root shell obtained](screenshots/root-shell-obtained.png)

### Flag 2

From there, the root flag was waiting in `/root`.

![root flag](screenshots/root-flag.png)

> **Security Issue #7:** Dangerous Linux Capability on a Non-Root Binary. Giving a binary the power to change its own user and group ID is functionally equivalent to handing out root access, and it bypasses the usual visibility that SUID bits get during a security review.

## Blue Team Perspective

Working back through this chain, here is what I think a defensive team would have caught, and where.

### 1. Exposed Subdomains and an Unauthenticated Internal API

Content discovery tools would have flagged the admin and API subdomains quickly, and the injectable parameter should never have been reachable without authentication in the first place. Fix: put internal APIs behind authentication and network segmentation, not just an unlisted hostname.

### 2. Password Reuse Across Accounts

The admin hash only fell because a password pattern from an unrelated table was reused. Fix: enforce unique, randomly generated credentials per account and monitor for password reuse across services during routine audits.

### 3. Weak Upload Filtering in the CMS Admin Panel

An extension blocklist is not real protection, and it gave an authenticated attacker a direct path to code execution. Fix: validate uploads by content type and use an allowlist rather than a blocklist, and serve uploaded files from a location that cannot execute code.

### 4. Excess Linux Capabilities Left on a Binary

A single `setcap` command turned a user owned utility into a root escalation path, and it would not have shown up in a routine SUID sweep. Fix: audit `getcap -r /` regularly, not just SUID bits, and remove capabilities that are not explicitly required.

![vulnet-endgame-complete](screenshots/Vulnnet%20Endgame%20-%20THM.jpg)

This write up is part of my ongoing series documenting CTF challenges as I build my portfolio in cybersecurity. I approach each challenge from both offensive and defensive perspectives, because understanding both sides is what makes a well rounded security professional.

If you are also on the journey toward a SOC or Security Engineering role, feel free to connect. I am always happy to discuss techniques and share resources.
