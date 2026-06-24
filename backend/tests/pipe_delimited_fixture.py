"""Synthetic upload CSV matching pipe-delimited EPP Status export patterns."""


def pipe_delimited_production_style_csv() -> bytes:
    """
    285-row export: 67 held (61 clientHold, 6 serverHold), 218 eligible.
    Domain State = Registered for all rows.
    """
    header = (
        "DNS Form,Create Date,EPP Status,Domain State,Registrar Name,Assigned Nameservers"
    )
    client_hold_patterns = [
        "clientTransferProhibited|clientHold|inactive",
        "clientTransferProhibited|clientHold|serverTransferProhibited|inactive",
        "clientTransferProhibited|serverTransferProhibited|clientHold|serverUpdateProhibited|inactive",
    ]
    server_hold_patterns = ["clientTransferProhibited|serverHold"]
    non_hold_patterns = [
        "clientTransferProhibited",
        "clientTransferProhibited|serverTransferProhibited",
        "clientTransferProhibited|inactive",
        "serverUpdateProhibited",
    ]
    rows = [header]
    idx = 0
    for _ in range(61):
        status = client_hold_patterns[idx % len(client_hold_patterns)]
        rows.append(
            f"row-{idx:04d}.example.test,2020-01-01,{status},Registered,Reg A,ns1.example.test"
        )
        idx += 1
    for _ in range(6):
        status = server_hold_patterns[0]
        rows.append(
            f"row-{idx:04d}.example.test,2020-01-01,{status},Registered,Reg A,ns1.example.test"
        )
        idx += 1
    while idx < 285:
        status = non_hold_patterns[idx % len(non_hold_patterns)]
        rows.append(
            f"row-{idx:04d}.example.test,2020-01-01,{status},Registered,Reg A,ns1.example.test"
        )
        idx += 1
    return "\n".join(rows).encode()
