class ProfileController:
    @staticmethod
    def initials(first_name: str, last_name: str, email: str) -> str:
        first = (first_name or "").strip()[:1].upper()
        last = (last_name or "").strip()[:1].upper()
        if first and last:
            return f"{first}{last}"
        if first:
            return first
        email_value = (email or "").strip()
        return email_value[:1].upper() if email_value else "?"
