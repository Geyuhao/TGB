"""
implement persistant forecast as baseline for the node prop pred task
simply predict last seen label for the node
"""

import time
import os.path as osp
from tqdm import tqdm
import torch
import numpy as np
from sklearn.metrics import ndcg_score
from torch_geometric.loader import TemporalDataLoader

# local imports
from tgb.nodeproppred.dataset_pyg import PyGNodePropertyDataset
from modules.heuristics import PersistantForecaster, MovingAverage
from tgb.nodeproppred.evaluate import Evaluator


device = "cpu"

#! first need to provide pyg dataset support for lastfm dataset

name = "un_trade"
dataset = PyGNodePropertyDataset(name=name, root="datasets")
num_classes = dataset.num_classes
data = dataset.get_TemporalData()
data = data.to(device)

forecaster = MovingAverage(num_classes)
evaluator = Evaluator(name=name)


# Ensure to only sample actual destination nodes as negatives.
min_dst_idx, max_dst_idx = int(data.dst.min()), int(data.dst.max())
train_data, val_data, test_data = data.train_val_test_split(
    val_ratio=0.15, test_ratio=0.15
)

batch_size = 200

train_loader = TemporalDataLoader(train_data, batch_size=batch_size)
val_loader = TemporalDataLoader(val_data, batch_size=batch_size)
test_loader = TemporalDataLoader(test_data, batch_size=batch_size)


def test_n_upate(loader):
    label_t = dataset.get_label_time()  # check when does the first label start
    num_labels = 0
    total_ndcg = 0

    for batch in tqdm(loader):
        batch = batch.to(device)
        src, pos_dst, t, msg = batch.src, batch.dst, batch.t, batch.msg

        query_t = batch.t[-1]
        if query_t > label_t:
            label_tuple = dataset.get_node_label(query_t)
            if label_tuple is None:
                break
            label_ts, label_srcs, labels = (
                label_tuple[0],
                label_tuple[1],
                label_tuple[2],
            )
            label_ts = label_ts.numpy()
            label_srcs = label_srcs.numpy()
            labels = labels.numpy()
            label_t = dataset.get_label_time()

            preds = []

            for i in range(0, label_srcs.shape[0]):
                node_id = label_srcs[i]
                pred_vec = forecaster.query_dict(node_id)
                preds.append(pred_vec)
                forecaster.update_dict(node_id, labels[i])

            np_pred = np.stack(preds, axis=0)
            np_true = labels

            input_dict = {"y_true": np_true, "y_pred": np_pred, "eval_metric": ["ndcg"]}
            result_dict = evaluator.eval(input_dict)
            ndcg = result_dict["ndcg"]

            total_ndcg += ndcg
            num_labels += label_ts.shape[0]

    metric_dict = {}
    metric_dict["ndcg"] = total_ndcg / num_labels
    return metric_dict


"""
train, val and test for one epoch only
"""

start_time = time.time()
metric_dict = test_n_upate(train_loader)
print(metric_dict)
print(
    "Persistant forecast on Training takes--- %s seconds ---"
    % (time.time() - start_time)
)

start_time = time.time()
val_dict = test_n_upate(val_loader)
print(val_dict)
print(
    "Persistant forecast on validation takes--- %s seconds ---"
    % (time.time() - start_time)
)


start_time = time.time()
test_dict = test_n_upate(test_loader)
print(test_dict)
print(
    "Persistant forecast on Test takes--- %s seconds ---" % (time.time() - start_time)
)
dataset.reset_label_time()
