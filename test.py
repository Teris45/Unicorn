
from transformers import BertTokenizer, RobertaTokenizer, AutoTokenizer, DebertaTokenizer, XLNetTokenizer, DistilBertTokenizer
import torch

import random
import csv
import argparse
import os
import time

from unicorn.model.encoder import (BertEncoder, MPEncoder, DistilBertEncoder, DistilRobertaEncoder, DebertaBaseEncoder, DebertaLargeEncoder,
                   RobertaEncoder, XLNetEncoder)
from unicorn.model.matcher import Classifier, MOEClassifier
from unicorn.model.moe import MoEModule
from unicorn.trainer import evaluate
from unicorn.utils.utils import get_data, init_model
from unicorn.dataprocess import predata
from unicorn.utils import param
import pandas as pd
import re
import json
import ast


def contains_ec_regex(s):
    return bool(re.search(r'_ec', s))

csv.field_size_limit(500 * 1024 * 1024)
def parse_arguments():
    # argument parsing
    parser = argparse.ArgumentParser(description="Specify Params for Experimental Setting")
    parser.add_argument('--pretrain', default=False, action='store_true',
                        help='Force to pretrain source encoder/moe/classifier')

    parser.add_argument('--seed', type=int, default=42,
                        help="Specify random state")

    parser.add_argument('--train_seed', type=int, default=42,
                        help="Specify random state")

    parser.add_argument('--load', default=False, action='store_true',
                        help="Load saved model")

    parser.add_argument('--model', type=str, default="bert",
                        help="Specify model type")

    parser.add_argument('--max_seq_length', type=int, default=128,
                        help="Specify maximum sequence length")

    parser.add_argument("--max_grad_norm", default=1.0, type=float,
                        help="Max gradient norm.")

    parser.add_argument("--clip_value", type=float, default=0.01,
                        help="lower and upper clip value for disc. weights")

    parser.add_argument('--batch_size', type=int, default=32,
                        help="Specify batch size")

    parser.add_argument('--pre_epochs', type=int, default=10,
                        help="Specify the number of epochs for pretrain")
        
    parser.add_argument('--pre_log_step', type=int, default=10,
                        help="Specify log step size for pretrain")

    parser.add_argument('--log_step', type=int, default=10,
                        help="Specify log step size for adaptation")

    parser.add_argument('--c_learning_rate', type=float, default=3e-6,
                        help="Specify lr for training")

    parser.add_argument('--num_cls', type=int, default=5,
                        help="")
    parser.add_argument('--num_tasks', type=int, default=2,
                        help="")

    parser.add_argument('--resample', type=int, default=0,
                        help="")
    parser.add_argument('--modelname', type=str, default="",
                        help="Specify saved model name")
    parser.add_argument('--ckpt', type=str, default="",
                        help="Specify loaded model name")
    parser.add_argument('--num_data', type=int, default=1000,
                        help="")
    parser.add_argument('--num_k', type=int, default=2,
                        help="")

    parser.add_argument('--scale', type=float, default=20, 
                    help="Use 20 for cossim, and 1 when you work with unnormalized embeddings with dot product")    
    
    parser.add_argument('--wmoe', type=int, default=1, 
                    help="with or without moe")
    parser.add_argument('--expertsnum', type=int, default=6, 
                    help="number of experts")
    parser.add_argument('--size_output', type=int, default=768,
                        help="encoder output size")
    parser.add_argument('--units', type=int, default=768, 
                    help="number of hidden")
    parser.add_argument('--shuffle', type=int, default=0, help="")
    parser.add_argument('--load_balance', type=int, default=0, help="")
    
    parser.add_argument('--dataset_path', type=str, default=None,
                        help="Specify dataset path")
    parser.add_argument('--test_metrics', type=str, default=None,
                        help="Metric for test dataset")
    
    
    return parser.parse_args()

args = parse_arguments()
def set_seed(seed):
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.device_count() > 0:
        torch.cuda.manual_seed_all(seed)

def main():
    if not args.dataset_path:
        print("Need to specify the test data path! ")
        exit(1)
    # argument setting
    print("=== Argument Setting ===")
    print("encoder: " + str(args.model))
    print("max_seq_length: " + str(args.max_seq_length))
    print("batch_size: " + str(args.batch_size))
    set_seed(args.train_seed)

    if args.model in ['roberta', 'distilroberta']:
        tokenizer = RobertaTokenizer.from_pretrained('roberta-base')
    if args.model == 'bert':
        tokenizer = BertTokenizer.from_pretrained('bert-base-multilingual-cased')
    if args.model == 'mpnet':
        tokenizer = AutoTokenizer.from_pretrained('sentence-transformers/all-mpnet-base-v2')
    if args.model == 'deberta_base':
        tokenizer = DebertaTokenizer.from_pretrained('microsoft/deberta-base')
    if args.model == 'deberta_large':
        tokenizer = DebertaTokenizer.from_pretrained('deberta-large')
    if args.model == 'xlnet':
        tokenizer = XLNetTokenizer.from_pretrained('xlnet-base-cased')
    if args.model == 'distilbert':
        tokenizer = DistilBertTokenizer.from_pretrained('distilbert/distilbert-base-uncased')

    if args.model == 'bert':
        encoder = BertEncoder()
    if args.model == 'mpnet':
        encoder = MPEncoder()
    if args.model == 'deberta_base':
        encoder = DebertaBaseEncoder()
    if args.model == 'deberta_large':
        encoder = DebertaLargeEncoder()
    if args.model == 'xlnet':
        encoder = XLNetEncoder()
    if args.model == 'distilroberta':
        encoder = DistilRobertaEncoder()
    if args.model == 'distilbert':
        encoder = DistilBertEncoder()
    if args.model == 'roberta':
        encoder = RobertaEncoder()
            
    if args.wmoe:
        classifiers = MOEClassifier(args.units) 
    else:
        classifiers = Classifier()
            
    if args.wmoe:
        exp = args.expertsnum
        moelayer = MoEModule(args.size_output,args.units,exp,load_balance=args.load_balance)
    
    if args.load:
        encoder = init_model(args, encoder, restore=args.ckpt+"_"+param.encoder_path)
        classifiers = init_model(args, classifiers, restore=args.ckpt+"_"+param.cls_path)
        if args.wmoe:
            moelayer = init_model(args, moelayer, restore=args.ckpt+"_"+param.moe_path)
    else:
        print("Unable to load the pre-trained Unicorn matching model, the initial Language Model will be used!")
        encoder = init_model(args, encoder)
        classifiers = init_model(args, classifiers)
        if args.wmoe:
            moelayer = init_model(args, moelayer)

            
    # test_sets = []
    # for p in args.dataset_path.split(" "):
    #     print("test data path: ", p)
    #     test_sets.append(get_data(p))
    
    if args.test_metrics is None:
        test_metrics = ['f1' for i in range(0, len(test_sets))]
    else:
        test_metrics = args.test_metrics.split(" ")

    datasets = ['eurocrops']
    type_ds = ['Joinable']
    results_folder = 'schema'
    for dataset in datasets: 
        for type_d in type_ds:
            directory_path = f'val-exp'
            results_filename = f'results/{results_folder}/unicorn_eurocrops.csv'
            
            if os.path.exists(results_filename):
                print(results_filename)
                continue

            if not os.path.exists(directory_path):
                raise FileNotFoundError(f"The path '{directory_path}' does not exist.")
                    
            # Print the immediate subfolders
            print(f"Immediate subfolders of '{directory_path}':")
            my_list = os.listdir(directory_path)
            cnt = 0
            for file in my_list:
                print(f"------ {cnt}/{len(my_list)} ------------ {dataset} {type_d} \n")
                if contains_ec_regex(file):
                    cnt += 1
                    continue
                
                file_path = f'{directory_path}/{file}'

                df_source = pd.read_csv(f"{file_path}/pyjedai/{file}_dbf.csv")
                df_target = pd.read_csv(f"{file_path}/pyjedai/{file}.csv")
                gtruth_filename = f'{file_path}/{file}.json'
                
                #read the json file
                with open(gtruth_filename, 'r') as f:
                    gtruth_data = json.load(f)
                
                matching_dict = {}

                for pair in gtruth_data['matches']:
                    matching_dict[pair['source_column']] = pair['target_column']

                
                test_data = []
                offset = df_source.shape[0]
                for _, row in df_source.iterrows():
                    source_str = f"[ATT] {row['attributes']}"
                    source_val = ""

                    # if isinstance(row['data'], str):
                    #     data_list = ast.literal_eval(row['data'])
                    #     val_list = " [VAL] ".join(data_list)
                    #     source_val = f" [VAL] {val_list}"


                    source_str += source_val
                    
                    for _, t_row in df_target.iterrows():
                        target_str = f"[ATT] {t_row['attributes']}"
                        target_val = ""
                        # if isinstance(t_row['data'], str):
                        #     t_data_list = ast.literal_eval(t_row['data'])
                        #     t_val_list = " [VAL] ".join(t_data_list)
                        #     target_val = f" [VAL] {t_val_list}"
                        target_str += target_val
                        matching = 0
                        if row['attributes'] in matching_dict and matching_dict[row['attributes']] == t_row['attributes']:
                            matching = 1
                        test_data.append([source_str, target_str, matching])
                start_time = time.perf_counter()
                fea = predata.convert_examples_to_features([ [x[0]+" [SEP] "+x[1]] for x in test_data ], [int(x[2]) for x in test_data], args.max_seq_length, tokenizer)
                test_data_loader = predata.convert_fea_to_tensor(fea, args.batch_size, do_train=0)
                f1, recall, precision = evaluate.evaluate_moe(encoder, moelayer, classifiers, test_data_loader, args=args, all=1)
                final_ev = {}
                final_ev['filename'] = file
                final_ev['model'] = args.model
                final_ev['time (sec)'] = time.perf_counter() - start_time
                final_ev['Precision %'] = precision * 100 
                final_ev['Recall %'] = recall * 100
                final_ev['F1 %'] = f1 * 100

                df_dictionary = pd.DataFrame([final_ev])
                cnt += 1

                if os.path.exists(results_filename):
                    df_dictionary.to_csv(results_filename, mode='a+', header=False, index=False)
                else:
                    df_dictionary.to_csv(results_filename, mode='a+', header=True, index=False)
    
    
    # dataset = 'wikidata'
    # d = {
    #     "Joinable" : "Musicians_joinable", 
    #     'Unionable': "Musicians_unionable",
    #     'View-Unionable': "Musicians_viewunion",
    #     'Semantically-Joinable' : "Musicians_semjoinable"
    # }
    
    # directory_path = f'data/val-exp/Wikidata/Musicians'
    # for type_d in type_ds:
    #     results_filename = f'results/{results_folder}/{dataset}_{type_d.lower()}.csv'
    
    #     if os.path.exists(results_filename):
    #         print(results_filename)
    #         continue

    #     if not os.path.exists(directory_path):
    #         raise FileNotFoundError(f"The path '{directory_path}' does not exist.")
            
    #     # Print the immediate subfolders
        
    #     file = d[type_d].lower()
    #     file_path = f'{directory_path}/{d[type_d]}'
        

    #     df_source = pd.read_csv(f"{file_path}/pyjedai/{file}_source.csv")
    #     df_target = pd.read_csv(f"{file_path}/pyjedai/{file}_target.csv")
    #     gtruth_filename = f'{file_path}/{file.lower()}_mapping.json'
        
    #     #read the json file
    #     with open(gtruth_filename, 'r') as f:
    #         gtruth_data = json.load(f)
        
    #     matching_dict = {}

    #     for pair in gtruth_data['matches']:
    #         matching_dict[pair['source_column']] = pair['target_column']

        
    #     test_data = []
    #     offset = df_source.shape[0]
    #     for _, row in df_source.iterrows():
    #         source_str = f"[ATT] {row['attributes']}"
    #         # source_val = ""

    #         # if isinstance(row['data'], str):
    #         #     data_list = ast.literal_eval(row['data'])
    #         #     val_list = " [VAL] ".join(data_list)
    #         #     source_val = f" [VAL] {val_list}"


    #         # source_str += source_val
            
    #         for _, t_row in df_target.iterrows():
    #             target_str = f"[ATT] {t_row['attributes']}"
    #             # target_val = ""
    #             # if isinstance(t_row['data'], str):
    #             #     t_data_list = ast.literal_eval(t_row['data'])
    #             #     t_val_list = " [VAL] ".join(t_data_list)
    #             #     target_val = f" [VAL] {t_val_list}"
    #             # target_str += target_val
    #             matching = 0
    #             if row['attributes'] in matching_dict and matching_dict[row['attributes']] == t_row['attributes']:
    #                 matching = 1
    #             test_data.append([source_str, target_str, matching])
    #     start_time = time.perf_counter()
    #     fea = predata.convert_examples_to_features([ [x[0]+" [SEP] "+x[1]] for x in test_data ], [int(x[2]) for x in test_data], args.max_seq_length, tokenizer)
    #     test_data_loader = predata.convert_fea_to_tensor(fea, args.batch_size, do_train=0)
    #     f1, recall, precision = evaluate.evaluate_moe(encoder, moelayer, classifiers, test_data_loader, args=args, all=1)
    #     final_ev = {}
    #     final_ev['filename'] = file
    #     final_ev['model'] = args.model
    #     final_ev['time (sec)'] = time.perf_counter() - start_time
    #     final_ev['Precision %'] = precision * 100 
    #     final_ev['Recall %'] = recall * 100
    #     final_ev['F1 %'] = f1 * 100

    #     df_dictionary = pd.DataFrame([final_ev])

    #     if os.path.exists(results_filename):
    #         df_dictionary.to_csv(results_filename, mode='a+', header=False, index=False)
    #     else:
    #         df_dictionary.to_csv(results_filename, mode='a+', header=True, index=False) 

    # test_data_loaders = []
    # for i in range(len(test_sets)):
    #     print("test dataset ", i+1)
    #     fea = predata.convert_examples_to_features([ [x[0]+" [SEP] "+x[1]] for x in test_sets[i] ], [int(x[2]) for x in test_sets[i]], args.max_seq_length, tokenizer)
    #     test_data_loaders.append(predata.convert_fea_to_tensor(fea, args.batch_size, do_train=0))

    # print("test datasets num: ",len(test_data_loaders))

    # f1s = []
    # recalls = []
    # accs = []
    # for k in range(len(test_data_loaders)):
    #     print("test datasets : ",k+1)
    #     if test_metrics[k]=='hit': # for EA
    #         prob = evaluate.evaluate_moe(encoder, moelayer, classifiers, test_data_loaders[k], args=args, flag="get_prob", prob_name="prob.json")
    #         evaluate.calculate_hits_k(test_sets[k], prob)
    #     else:
    #         f1, recall, acc = evaluate.evaluate_moe(encoder, moelayer, classifiers, test_data_loaders[k], args=args, all=1)
    #         f1s.append(f1)
    #         recalls.append(recall)
    #         accs.append(acc)
    # print("F1: ", f1s)
    # print("Recall: ", recalls)
    # print("ACC.", accs)
                
                

if __name__ == '__main__':
    main()
