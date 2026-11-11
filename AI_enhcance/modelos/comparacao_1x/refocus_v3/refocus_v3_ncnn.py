import numpy as np
import ncnn
import torch

def test_inference():
    torch.manual_seed(0)
    in0 = torch.rand(1, 3, 64, 64, dtype=torch.float)
    out = []

    with ncnn.Net() as net:
        net.load_param("/home/gabriel/Transferências/modelos/comparacao_1x/refocus_v3/refocus_v3.ncnn.param")
        net.load_model("/home/gabriel/Transferências/modelos/comparacao_1x/refocus_v3/refocus_v3.ncnn.bin")

        with net.create_extractor() as ex:
            ex.input("in0", ncnn.Mat(in0.numpy(), batch_index=0).clone())

            _, out0 = ex.extract("out0")
            out.append(torch.from_numpy(out0.numpy(batch_index=0)))

    if len(out) == 1:
        return out[0]
    else:
        return tuple(out)

if __name__ == "__main__":
    print(test_inference())
