from app.map_proxy import build_baidu_vector_tile_params, encode_baidu_tile_descriptor


def test_baidu_tile_descriptor_matches_mapv_three_encoding():
    descriptor = "x=M1&y=-2&z=7&styles=pl&textimg=0&v=088&udt=20250110&json=0"

    assert encode_baidu_tile_descriptor(descriptor) == (
        "5J9G8E4;EK9FHE6;EL9FMD>NMFA7H8<NKO@3H4>O57A3L8DM=99FJ4>OCO82N5B;EG>CL5L>CB8:LE2>;C82E8FNMA?JPE23"
    )


def test_baidu_tile_params_keep_coordinates_and_use_server_ak():
    params = build_baidu_vector_tile_params("M1", "-2", 7, "server-ak")

    assert params["qt"] == "vtile"
    assert params["v"] == "three"
    assert params["ak"] == "server-ak"
    assert "client-ak" not in params["param"]
    assert params["param"] == encode_baidu_tile_descriptor(
        "x=M1&y=-2&z=7&styles=pl&textimg=0&v=088&udt=20250110&json=0"
    )
