# Rabbit Store Writeup

**Machine Name:** Rabbit Store  
**Platform:** TryHackMe  
**Difficulty:** Medium

---

![display](screenshots/display.jpg)

## Introduction

Rabbit Store is a medium web focused room on TryHackMe. The description asks you to test a web application and then use some basic Linux knowledge to climb to root, and that is a fair summary of how the box plays out.

Nothing here falls into your lap. Every step earns the next one. A subscription check that trusts the client hands over a working account. That account exposes an upload feature that fetches URLs for you, which becomes a way to reach the machine's own internal ports. One of those ports serves an internal API guide, the guide points at a chatbot endpoint, and the chatbot renders whatever you send it. Rendering user input is code execution. After that the box is all about RabbitMQ, and a single reused password finishes it.

## Phase 1: Enumeration

I started with a full TCP port scan and version detection.

```
nmap -p- -sV -sC <TARGET_IP>
```

Four ports answered:

```
22/tcp    open  ssh     OpenSSH 8.9p1 Ubuntu
80/tcp    open  http    Apache httpd 2.4.52
4369/tcp  open  epmd    Erlang Port Mapper Daemon
25672/tcp open  unknown
```

The HTTP title tried to redirect to `http://cloudsite.thm/`, so I added that hostname to my `/etc/hosts` file. The two unusual ports, 4369 and 25672, are worth flagging early. Port 4369 is the Erlang Port Mapper Daemon, and the scan even named the node behind it: `rabbit` on 25672. In plain terms, RabbitMQ is running on this box. I filed that away and went to the website.

The site is a clean marketing page with a login button. Clicking login bounces you to a subdomain.

![web homepage](screenshots/01-web-homepage.png)

![login page](screenshots/02-login-page.png)

## Phase 2: Content Discovery

I ran a directory scan against the main site and against the `storage.cloudsite.thm` subdomain that the app uses.

![dirsearch main](screenshots/03-dirsearch-cloudsite.png)

![dirsearch storage](screenshots/04-dirsearch-storage.png)

Nothing useful came back, which is fine. An empty scan still tells you where to look next. The real attack surface here is behind the login, so that is where I spent my time.

## Phase 3: Forging an Active Account

I registered a normal account and logged in. The dashboard made two things obvious. This portal is meant for internal users only, and access depends on your subscription being active.

![signup](screenshots/05-signup.png)

![internal users only](screenshots/06-login-internal-users.png)

After logging in I was handed a JWT. Decoding it at jwt.io showed a `subscription` field set to `inactive`.

![jwt in dashboard](screenshots/07-jwt-in-dashboard.png)

![jwt decoded inactive](screenshots/08-jwt-decoded-inactive.png)

The lazy move is to edit the token and flip `inactive` to `active`.

![edit jwt attempt](screenshots/09-jwt-edit-attempt.png)

That fails, and it should. The server signs the token with a secret I do not have, so any change I make breaks the signature and the token gets rejected as invalid.

![invalid token](screenshots/10-invalid-token.png)

So I attacked the step before the token exists. Instead of tampering with a signed token, I registered a fresh account and intercepted the registration request in Burp. The signup form only asks for an email and a password, but nothing stops me from adding my own field to the request body. I added `subscription: active` and forwarded it.

![new account](screenshots/11-new-account.png)

![intercept register](screenshots/12-intercept-register.png)

![inject subscription active](screenshots/13-inject-subscription-active.png)

![forward request](screenshots/14-forward-request.png)

The server took the extra field at face value and built my account with an active subscription baked in. Now when I log in, the token it signs already says `active`, and the dashboard opens up.

![login active](screenshots/15-login-active.png)

![jwt active](screenshots/16-jwt-active.png)

> **Security Issue #1:** Mass Assignment on Registration. The registration endpoint trusted a field the client had no business setting. A user should never be able to grant themselves a paid or privileged status just by adding it to the request body.

## Phase 4: Testing the Upload Feature

With the dashboard open, the main feature is file upload. I uploaded a plain text file and it worked.

![file upload](screenshots/17-file-upload-txt.png)

The catch is that the path it gives back is not reachable from the browser. It looks like an internal path, so smuggling in a reverse shell file and browsing to it is a dead end.

![path not accessible](screenshots/18-upload-path-internal.png)

Scrolling down, there is a second option: upload a file from a URL. A note beside it warns that only certain file types are allowed, which rules out the obvious shell upload.

![upload from url](screenshots/19-upload-from-url.png)

![upload restriction](screenshots/20-upload-restriction.png)

That "fetch from a URL" feature is the part I kept in mind. Any time a server fetches a URL you give it, the next question is what else you can point it at.

## Phase 5: Finding a Hidden API

Looking at the requests the app makes, I could see endpoints like `/api/upload`, `/uploads`, and `/login`, plus a logout route. That was enough of a pattern to fuzz for more, so I ran ffuf against the API path.

![api endpoints in request](screenshots/21-api-endpoints-in-request.png)

![ffuf fuzzing](screenshots/22-ffuf-fuzzing.png)

Fuzzing turned up one new route: `/api/docs`. Browsing to it directly returned 403 Forbidden, so it is meant for internal eyes only. Which is interesting, because I already have a feature that fetches URLs on the server's behalf.

![api docs 403](screenshots/23-api-docs-403.png)

## Phase 6: SSRF Into the Internal Network

I pointed the "upload from URL" feature at the docs endpoint. The idea is simple. I cannot read `/api/docs`, but maybe the server can, and it will fetch the result for me. That kind of trick is called server side request forgery.

![ssrf docs attempt](screenshots/24-ssrf-docs-attempt.png)

The feature returned a stored file path for whatever it fetched.

![ssrf file path](screenshots/25-ssrf-file-path.png)

When I retrieved that stored file, a direct request to the docs hostname still came back with access denied, but the behaviour proved the server was making requests for me.

![ssrf fetch url](screenshots/26-ssrf-fetch-url.png)

![ssrf access denied](screenshots/27-ssrf-access-denied.png)

So I aimed it inward at `127.0.0.1` instead of the hostname. Same feature, except now the server is talking to itself, which is exactly what the access control was trying to prevent.

![ssrf localhost](screenshots/28-ssrf-localhost.png)

![ssrf localhost path](screenshots/29-ssrf-localhost-path.png)

The first localhost attempt hit the wrong port, so I wrote a short script to brute force the ports through the same SSRF, watching for a response that returned a valid path.

![ssrf wrong port](screenshots/30-ssrf-wrong-port.png)

![port bruteforce script](screenshots/31-port-bruteforce-script.png)

![port bruteforce run](screenshots/32-port-bruteforce-run.png)

Two ports answered internally: 80 and 3000.

![open ports](screenshots/33-open-ports.png)

Fetching `http://127.0.0.1:3000/api/docs` finally returned the internal API guide, the same page that was forbidden from the outside. It lists every endpoint the app has, including a file viewer and a chatbot route that is still under development.

![internal api docs](screenshots/34-internal-api-docs.png)

> **Security Issue #2:** SSRF Through a URL Fetch Feature. The upload from URL feature would fetch any address it was given, including the server's own loopback interface. That let me reach internal ports and read an API guide that was supposed to be off limits.

## Phase 7: The Chatbot Endpoint and SSTI

The file viewer route came back empty, so the chatbot endpoint was the one to chase. A GET request returned "method not allowed", so I switched it to POST in Burp. That gave a 500 error whose message was JSON, which hints at how the endpoint wants to be fed. I added a `Content-Type: application/json` header and a `username` parameter.

![uploads api empty](screenshots/35-uploads-api-empty.png)

![chatbot get not allowed](screenshots/36-chatbot-get-not-allowed.png)

![chatbot post 500](screenshots/37-chatbot-post-500.png)

![chatbot content type](screenshots/38-chatbot-content-type.png)

![chatbot username param](screenshots/39-chatbot-username-param.png)

![chatbot response](screenshots/40-chatbot-response.png)

Then the standard test for server side template injection. I set the username to `{{7*7}}`. If the app just echoes it back, there is no bug. If it renders `49`, it is evaluating my input as a template.

![ssti confirmed](screenshots/41-ssti-confirmed.png)

The response came back as "Sorry, 49, our chatbot server is currently under development." It did the math, which confirms a Jinja2 template injection.

## Phase 8: From SSTI to a Shell

Template injection in Jinja2 is a short walk to running commands. I used a known payload that reaches through Python's object model to import `os` and run a command. Sending `id` confirmed code execution, running as the user `azrael`.

![ssti rce id](screenshots/42-ssti-rce-id.png)

From there I generated a base64 encoded bash reverse shell, dropped it into the same payload, and started a listener.

![revshell generator](screenshots/43-revshell-generator.png)

![revshell payload](screenshots/44-revshell-payload.png)

![revshell execute](screenshots/45-revshell-execute.png)

The callback landed and gave me an interactive shell as azrael.

![listener shell](screenshots/46-listener-shell.png)

> **Security Issue #3:** Template Injection in the Chatbot. User input was dropped straight into a template and rendered, which let me run code on the server. Untrusted input should never be treated as part of a template.

### First flag

With a shell as azrael, the user flag was sitting in the home directory.

![user flag](screenshots/47-user-flag.png)

## Phase 9: Following the RabbitMQ Trail

Home held a single user, so I looked wider. Reading `/etc/passwd` showed a `rabbitmq` service account, which lines up with the Erlang ports from the very first scan.

![home listing](screenshots/48-home-listing.png)

![passwd rabbitmq](screenshots/49-passwd-rabbitmq.png)

RabbitMQ runs on Erlang, and Erlang nodes prove their identity to each other with a shared secret stored in a file called the Erlang cookie. I checked the RabbitMQ data directory and the cookie was readable.

![rabbitmq directory](screenshots/50-rabbitmq-directory.png)

![erlang cookie](screenshots/51-erlang-cookie.png)

## Phase 10: Erlang Cookie to a RabbitMQ Shell

Anyone holding the Erlang cookie can talk to the node as a trusted peer, and there is a public Metasploit module that turns that into code execution. I loaded `exploit/multi/misc/erlang_cookie_rce`, set the target, the cookie, and port 25672, and ran it. One thing to note: the callback only worked from the TryHackMe AttackBox, so the listener host had to match that.

![msf erlang module](screenshots/52-msf-erlang-module.png)

![msf options](screenshots/53-msf-options.png)

The module authenticated with the cookie and dropped me into a shell as the `rabbitmq` user.

![msf rabbitmq shell](screenshots/54-msf-rabbitmq-shell.png)

## Phase 11: Privilege Escalation to Root

As the rabbitmq user I could finally run `rabbitmqctl`, the admin tool for the message broker. It first complained that the cookie file had to be readable by its owner only, so I fixed the permissions with `chmod 600`.

![rabbitmqctl cookie error](screenshots/55-rabbitmqctl-cookie-error.png)

![chmod cookie](screenshots/56-chmod-cookie.png)

Listing the users gave me the lead I needed. There is a `root` user with administrator rights, and a message on screen says the Linux root password is the SHA-256 value of the RabbitMQ root user's password.

![listusers hint](screenshots/57-listusers-hint.png)

RabbitMQ can export its full configuration, password hashes included, so I exported the definitions to a file and pulled it back to my machine.

![export definitions](screenshots/58-export-definitions.png)

![cat definitions](screenshots/59-cat-definitions.png)

![save definitions](screenshots/60-save-definitions.png)

Running it through `jq` laid the JSON out cleanly, and the part I cared about is the root user's password hash.

![jq parse](screenshots/61-jq-parse.png)

![password hash](screenshots/62-password-hash.png)

RabbitMQ stores that hash in a specific shape. It is base64, and once you decode it to raw bytes the first four bytes are a salt with the SHA-256 value right after. So I decoded the hash from base64 to hex and dropped the first eight hex characters, which is that four byte salt. What is left is the SHA-256 value the hint was pointing at.

![decode base64 to hex](screenshots/63-decode-base64-to-hex.png)

![strip salt bytes](screenshots/64-strip-salt-bytes.png)

That value is the actual Linux root password. I ran `su`, pasted it in, and I was root.

![su root](screenshots/65-su-root.png)

![whoami root](screenshots/66-whoami-root.png)

> **Security Issue #4:** Reused and Exposed Credentials. The Erlang cookie was readable, and the RabbitMQ root hash decoded straight into the Linux root password. One readable file and a bit of decoding was enough to own the whole box.

### Flag 2

With root, the final flag was waiting in `/root`.

![root flag](screenshots/67-root-flag.png)

## Blue Team Perspective

Walking back through the chain, here is where a defender would have had a chance to stop me.

### 1. Mass Assignment on Registration

Letting a client set its own subscription status is an access control failure. The server should decide privileged fields on its own and ignore anything the client sends for them. A registration request that suddenly carries a `subscription` field is also worth an alert.

### 2. SSRF in the URL Fetch Feature

A feature that fetches user supplied URLs should never be able to reach internal addresses. Block requests to loopback and private ranges, allow only the destinations the feature actually needs, and stop treating a 403 as if it hides the page from someone already inside the network.

### 3. Template Injection in the Chatbot

User input rendered as a template is remote code execution waiting to happen. Keep user input out of template logic entirely, and validate what the chatbot accepts. An endpoint that returns `7*7` as `49` is the kind of finding a code review or a scanner should catch before release.

### 4. Reused and Weakly Protected Credentials

The Erlang cookie should be locked down so a low privilege user cannot read it, and the RabbitMQ root password should never double as the Linux root login. Unique credentials per system and a real secrets store would have broken the last step of this chain.

![completion](screenshots/Rabbit%20Store%20-%20THM.jpg)

This write-up is part of my ongoing series documenting CTF challenges as I build my portfolio in cybersecurity. I look at each box from both the attacker's side and the defender's side, because being able to explain where an attack could have been stopped matters as much as pulling it off.

If you are also working toward a SOC or security role, feel free to connect. I am always happy to compare notes and swap resources.
