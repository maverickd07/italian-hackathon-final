"""Shared R12 policy: personal mailbox domains are not company identities.

Observed providers plus common variants; not an exhaustive worldwide freemail registry.
Explicit source/API associations are never removed by this rule.
"""

FREE_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "libero.it",
        "yahoo.com",
        "yahoo.it",
        "yahoo.co.uk",
        "hotmail.com",
        "hotmail.it",
        "hotmail.co.uk",
        "outlook.com",
        "outlook.it",
        "live.com",
        "live.it",
        "msn.com",
        "tiscali.it",
        "icloud.com",
        "me.com",
        "aol.com",
        "virgilio.it",
        "alice.it",
        "tin.it",
        "proton.me",
        "protonmail.com",
    }
)


def company_email_domain(email):
    if not isinstance(email, str) or email.count("@") != 1:
        return ""
    local, host = email.strip().lower().split("@")
    if (
        not local
        or "." not in host
        or any(c.isspace() for c in email)
        or host in FREE_EMAIL_DOMAINS
    ):
        return ""
    return host
