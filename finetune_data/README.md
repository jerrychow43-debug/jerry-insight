# Jerry Money Agent LoRA Data

Generated training assets for the Jerry Insight Pro fine-tuning demo.

- Train samples: 155
- Test samples: 50
- Task: user spending text -> strict JSON intent/entity/action parse

Upload these files to AutoDL LLaMA-Factory:

- jerry_money_agent_train.json -> /root/autodl-tmp/LLaMA-Factory/data/
- jerry_money_agent_test.json -> /root/autodl-tmp/LLaMA-Factory/data/
- jerry_money_agent_lora_v2.yaml -> /root/autodl-tmp/LLaMA-Factory/examples/train_lora/
- jerry_money_agent_lora_v2_infer.yaml -> /root/autodl-tmp/LLaMA-Factory/examples/inference/
