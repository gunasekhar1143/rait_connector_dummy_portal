---
description: Run an end-to-end RSA encryption roundtrip validation for a RAIT encryptor class. Pass the class name (Encryptor or EncryptorV2) and the plaintext string to test.
argument-hint: "<EncryptorClass> \"<plaintext-string>\""
allowed-tools: Bash, Read
---

Run an encryption roundtrip validation:

$ARGUMENTS

Execution steps:
1. Load RSA key pair from keys/ directory
2. Instantiate the specified Encryptor class (Encryptor or EncryptorV2)
3. Encrypt the specified test plaintext string
4. Print the hex dump of the first 32 bytes of the encrypted output
5. Report: version byte (byte 0), key_len value (bytes 0-3 little-endian), interpreted value
6. Instantiate DecryptionEngine with the private key
7. Call decrypt() with the base64-encoded encrypted output
8. Assert decrypted bytes == original plaintext encoded as UTF-8

If assertion passes: print PASS with hex evidence.
If assertion fails: print FAIL, print hex dump of raw bytes, report which parsing step produced wrong result.
Do not proceed past a FAIL — fix DecryptionEngine._decrypt_package() endianness first.
