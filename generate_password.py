from getpass import getpass
from store import password_hash
if __name__=='__main__':
    password=getpass('Choose admin password (at least 12 characters): ')
    if password!=getpass('Repeat password: '):raise SystemExit('Passwords do not match.')
    print('Copy this hash into ADMIN_PASSWORD_HASH in Streamlit Secrets:')
    print(password_hash(password))
