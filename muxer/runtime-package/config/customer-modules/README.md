RPDB local customer-module staging lives here.

Preferred layout:

- `config/customer-modules/<customer>/customer-module.json`

Also accepted for convenience:

- `config/customer-modules/<customer>.json`
- `config/customer-modules/<customer>.yaml`

This path is for isolated validation or bundle staging when the runtime is not
reading customers from DynamoDB.
